"""Sending email: Settings → Admin → Email, "Forgot password?" and emailed invites, against a fake SMTP server."""

import re
import sqlite3

import pytest

from conftest import CSRF_HEADERS
from support.smtp import FakeSMTP, body
from test_auth import PASSWORD, client_for, set_up

NEW_PASSWORD = "a brand new passphrase"


@pytest.fixture
def smtp():
    fake = FakeSMTP()
    yield fake
    fake.close()


def mail_env(smtp: FakeSMTP) -> dict:
    return {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(smtp.port), "SMTP_SECURITY": "none",
            "SMTP_FROM": "feedstash@example.com", "DEV_LOGIN": "false"}


def reset_token(msg) -> str:
    return re.search(r"/reset#([\w-]+)", body(msg)).group(1)


def test_forgot_password_emails_a_one_use_link_that_sets_a_new_password(start_server, smtp):
    server = start_server(**mail_env(smtp), BASE_URL="https://reader.example.com,http://localhost:9")
    owner = set_up(server)
    assert "Forgot password?" in client_for(server).get("/").text

    sent = client_for(server).post("/auth/forgot", json={"email": " Owner@Example.com "})
    assert sent.status_code == 200 and "If that address has an account" in sent.json()["detail"]
    [msg] = smtp.wait_for(1)
    assert msg["To"] == "owner@example.com" and msg["Subject"] == "Reset your FeedStash password"
    assert "FeedStash <feedstash@example.com>" in msg["From"]
    token = reset_token(msg)

    stranger = client_for(server)
    assert stranger.get("/reset").status_code == 200
    assert stranger.post("/auth/reset/check", json={"token": token}).json() == {"usable": True, "detail": None}
    short = stranger.post("/auth/reset", json={"token": token, "password": "short"})
    assert short.status_code == 400
    done = stranger.post("/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert done.status_code == 200, done.text
    assert stranger.get("/api/me").json()["email"] == "owner@example.com"  # signed in with the new password

    assert owner.get("/api/me").status_code == 401  # every other browser is signed out
    assert client_for(server).post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 401
    assert client_for(server).post("/auth/password", json={"email": "owner@example.com", "password": NEW_PASSWORD}).status_code == 200

    again = client_for(server).post("/auth/reset", json={"token": token, "password": "another passphrase"})
    assert again.status_code == 404 and "has been used" in again.json()["detail"]
    assert client_for(server).post("/auth/reset/check", json={"token": token}).json()["usable"] is False


def test_unknown_addresses_get_the_same_answer_and_no_email(start_server, smtp):
    server = start_server(**mail_env(smtp))
    set_up(server)
    known = client_for(server).post("/auth/forgot", json={"email": "owner@example.com"})
    unknown = client_for(server).post("/auth/forgot", json={"email": "nobody@example.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    smtp.wait_for(2, timeout=3)
    assert [m["To"] for m in smtp.messages] == ["owner@example.com"]


def test_a_second_request_replaces_the_first_link_and_requests_are_limited(start_server, smtp):
    server = start_server(**mail_env(smtp))
    set_up(server)
    client = client_for(server)
    # Each email is waited for before the next is asked for: sent together, they can arrive in either order.
    client.post("/auth/forgot", json={"email": "owner@example.com"})
    first = reset_token(smtp.wait_for(1)[0])
    client.post("/auth/forgot", json={"email": "owner@example.com"})
    second = reset_token(smtp.wait_for(2)[1])
    assert client.post("/auth/reset/check", json={"token": first}).json()["usable"] is False
    assert client.post("/auth/reset/check", json={"token": second}).json()["usable"] is True
    client.post("/auth/forgot", json={"email": "owner@example.com"})
    limited = client.post("/auth/forgot", json={"email": "owner@example.com"})
    assert limited.status_code == 429 and "Too many reset requests" in limited.json()["detail"]


def test_an_expired_link_doesnt_work(start_server, smtp):
    server = start_server(**mail_env(smtp))
    set_up(server)
    client_for(server).post("/auth/forgot", json={"email": "owner@example.com"})
    token = reset_token(smtp.wait_for(1)[0])
    with sqlite3.connect(server.db_path) as db:
        db.execute("UPDATE password_resets SET expires_at = 0")
    late = client_for(server).post("/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert late.status_code == 404 and "expired" in late.json()["detail"]


def test_without_email_there_is_no_forgot_password(start_server):
    server = start_server(DEV_LOGIN="false")
    set_up(server)
    assert "Forgot password?" not in client_for(server).get("/").text
    assert client_for(server).post("/auth/forgot", json={"email": "owner@example.com"}).status_code == 404


def test_admins_set_up_email_in_settings_and_send_a_test(start_server):
    fake = FakeSMTP(require_auth=("mailer", "s3cret pass"))
    try:
        server = start_server(DEV_LOGIN="false")
        admin = set_up(server)
        assert admin.get("/api/admin/email").json()["source"] == "none"
        saved = admin.put("/api/admin/email", json={
            "host": "127.0.0.1", "port": fake.port, "security": "none", "username": "mailer",
            "password": "s3cret pass", "from_address": "News@Example.com", "from_name": "My  FeedStash",
        })
        assert saved.status_code == 200, saved.text
        out = saved.json()
        assert out["source"] == "app" and out["ready"] is True and out["has_password"] is True
        assert out["from_address"] == "news@example.com" and out["from_name"] == "My FeedStash"
        assert "password" not in out and "s3cret" not in saved.text  # never sent back

        with sqlite3.connect(server.db_path) as db:
            stored = dict(db.execute("SELECT key, value FROM app_settings WHERE key LIKE 'email.%'").fetchall())
        assert stored["email.password"] and "s3cret" not in stored["email.password"]  # encrypted

        assert admin.post("/api/admin/email/test", json={}).status_code == 200
        [msg] = fake.wait_for(1)
        assert msg["To"] == "owner@example.com" and msg["Subject"] == "FeedStash can send email"

        # Saving again without a password keeps it; a wrong one is reported in words.
        admin.put("/api/admin/email", json={**out, "password": None})
        assert admin.post("/api/admin/email/test", json={}).status_code == 200
        admin.put("/api/admin/email", json={**out, "password": "wrong"})
        failed = admin.post("/api/admin/email/test", json={})
        assert failed.status_code == 502 and "didn't accept the username and password" in failed.json()["detail"]

        assert admin.delete("/api/admin/email").json()["source"] == "none"
        assert "Forgot password?" not in client_for(server).get("/").text
    finally:
        fake.close()


def test_members_cant_see_or_change_email_settings(start_server, smtp):
    server = start_server(**mail_env(smtp))
    admin = set_up(server)
    admin.post("/api/accounts", json={"email": "member@example.com", "password": PASSWORD})
    member = client_for(server)
    member.post("/auth/password", json={"email": "member@example.com", "password": PASSWORD})
    assert member.get("/api/admin/email").status_code == 403
    assert member.put("/api/admin/email", json={"host": "x", "from_address": "a@b.co"}).status_code == 403
    assert member.post("/api/admin/email/test", json={}).status_code == 403
    assert client_for(server).get("/api/admin/email", headers=CSRF_HEADERS).status_code == 401


def test_invites_can_be_emailed(start_server, smtp):
    server = start_server(**mail_env(smtp), BASE_URL="https://reader.example.com,http://localhost:9")
    admin = set_up(server)
    invite = admin.post("/api/invites", json={"email": "ann@example.com", "days": 7, "send_email": True}).json()
    assert invite["emailed"] is True and invite["email_error"] is None
    [msg] = smtp.wait_for(1)
    assert msg["To"] == "ann@example.com" and msg["Subject"] == "Owner invited you to FeedStash"
    assert invite["links"][0] in body(msg)

    no_address = admin.post("/api/invites", json={"days": 7, "send_email": True})
    assert no_address.status_code == 400


def test_an_invite_that_cant_be_emailed_still_stands(start_server):
    server = start_server(DEV_LOGIN="false", SMTP_HOST="127.0.0.1", SMTP_PORT="9", SMTP_SECURITY="none",
                          SMTP_FROM="feedstash@example.com")
    admin = set_up(server)
    invite = admin.post("/api/invites", json={"email": "ann@example.com", "days": 7, "send_email": True}).json()
    assert invite["emailed"] is False and "Couldn't reach 127.0.0.1:9" in invite["email_error"]
    assert invite["links"] and [i["id"] for i in admin.get("/api/invites").json()] == [invite["id"]]
