"""MANAGED (a host looks after email, sign-in and logs), ACCOUNT_LIMIT and STORAGE_LIMIT_GB."""

import pytest

from support.images import PNG
from support.smtp import FakeSMTP
from test_auth import CLIENT_ID, CLIENT_SECRET, PASSWORD, client_for, set_up


@pytest.fixture
def smtp():
    fake = FakeSMTP()
    yield fake
    fake.close()


def test_a_managed_server_keeps_email_sign_in_and_logs_for_its_host(start_server, smtp):
    server = start_server(DEV_LOGIN="false", MANAGED="true", SMTP_HOST="127.0.0.1", SMTP_PORT=str(smtp.port),
                          SMTP_SECURITY="none", SMTP_FROM="no-reply@example.com")
    admin = set_up(server)
    info = admin.get("/api/server").json()
    assert info["managed"] is True and info["can_email"] is True
    for path in ("/api/admin/email", "/api/admin/sign-in", "/api/admin/logs/settings"):
        refused = admin.get(path)
        assert refused.status_code == 403 and "hosts this FeedStash" in refused.json()["detail"], path
    assert admin.put("/api/admin/email", json={"host": "evil.example.com", "from_address": "a@b.co"}).status_code == 403
    assert admin.post("/api/admin/email/test", json={}).status_code == 403
    # Email the host set up still works for everyone: Forgot password and emailed invites.
    assert client_for(server).post("/auth/forgot", json={"email": "owner@example.com"}).status_code == 200
    invite = admin.post("/api/invites", json={"email": "kid@example.com", "days": 7, "send_email": True}).json()
    assert invite["emailed"] is True
    assert {m["To"] for m in smtp.wait_for(2)} == {"owner@example.com", "kid@example.com"}


def test_an_unmanaged_server_says_so(start_server):
    api = start_server().login()
    assert api.get("/api/server").json() == {
        "managed": False, "account_limit": 0, "can_email": False, "storage_used": api.get("/api/server").json()["storage_used"],
        "storage_limit": 0}
    assert api.get("/api/admin/email").status_code == 200


def test_the_account_limit_counts_accounts_and_unused_invites(start_server):
    server = start_server(DEV_LOGIN="false", ACCOUNT_LIMIT="3")
    admin = set_up(server)
    assert admin.get("/api/server").json()["account_limit"] == 3
    assert admin.post("/api/accounts", json={"email": "two@example.com", "password": PASSWORD}).status_code == 201
    invite = admin.post("/api/invites", json={"days": 7})
    assert invite.status_code == 201
    over = admin.post("/api/invites", json={"days": 7})
    assert over.status_code == 409 and "room for 3 accounts, counting invites" in over.json()["detail"]
    full = admin.post("/api/accounts", json={"email": "four@example.com", "password": PASSWORD})
    assert full.status_code == 201  # 2 accounts + 1 unused invite: an account itself still fits
    token = invite.json()["links"][0].split("#", 1)[1]
    late = client_for(server).post("/auth/invite", json={"token": token, "email": "guest@example.com", "password": PASSWORD})
    assert late.status_code == 409 and "room for 3 accounts" in late.json()["detail"]
    assert admin.post("/api/accounts", json={"email": "five@example.com", "password": PASSWORD}).status_code == 409


def test_a_full_server_stops_new_saves_but_keeps_everything_else(start_server):
    server = start_server(STORAGE_LIMIT_GB="0.000001")  # about 1 KB: an empty database is already bigger
    api = server.login()
    info = api.get("/api/server").json()
    assert info["storage_limit"] == 1073 and info["storage_used"] > info["storage_limit"]
    saved = api.post("/api/items", json={"type": "link", "url": "https://example.com/a"})
    assert saved.status_code == 507 and "storage is full" in saved.json()["detail"]
    picture = api.post("/api/items", data={"type": "screenshot"}, files={"image": ("s.png", PNG, "image/png")})
    assert picture.status_code == 507
    assert api.post("/api/items/import", json={"links": [{"url": "https://example.com/b"}]}).status_code == 507
    assert api.post("/api/account/import", files={"file": ("x.zip", b"x", "application/zip")}).status_code == 507
    assert api.get("/api/items").status_code == 200  # reading, and everything else, carries on
    assert api.post("/api/folders", json={"name": "Still fine"}).status_code in (200, 201)


def test_a_first_single_sign_on_past_the_limit_is_turned_away(start_server, oidc_provider):
    server = start_server(
        DEV_LOGIN="false", PASSWORD_LOGIN="false", ALLOWED_EMAILS="*", ACCOUNT_LIMIT="1", OIDC_ISSUER=oidc_provider.issuer,
        OIDC_CLIENT_ID=CLIENT_ID, OIDC_CLIENT_SECRET=CLIENT_SECRET,
    )
    oidc_provider.claims = {"sub": "ann-1", "email": "ann@example.com", "email_verified": True}
    ann = client_for(server, follow_redirects=True)
    ann.get("/auth/login/oidc")
    assert ann.get("/api/me").json()["email"] == "ann@example.com"
    oidc_provider.claims = {"sub": "bob-1", "email": "bob@example.com", "email_verified": True}
    turned_away = client_for(server, follow_redirects=True).get("/auth/login/oidc")
    assert turned_away.url.params.get("error") == "full" and "no room for another account" in turned_away.text
    # Ann signing in again isn't a new account, so the limit doesn't stop her.
    oidc_provider.claims = {"sub": "ann-1", "email": "ann@example.com", "email_verified": True}
    again = client_for(server, follow_redirects=True)
    again.get("/auth/login/oidc")
    assert again.get("/api/me").json()["email"] == "ann@example.com"
