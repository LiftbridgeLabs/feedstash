"""Pre-launch hardening: who may set up a new server, signing other browsers out, and the mailbox password."""

import httpx

from conftest import CSRF_HEADERS
from test_auth import PASSWORD, client_for, set_up

OUTSIDE = {"X-Forwarded-For": "93.184.216.34"}  # the test server trusts its own address as a proxy, as one would
NEW_PASSWORD = "a brand new password"


# ------------------------------------------------------------------ first-run setup


def test_setup_from_outside_the_network_is_refused_and_explained(start_server):
    server = start_server(DEV_LOGIN="false")
    page = httpx.get(server.base_url + "/", headers=OUTSIDE).text
    assert 'data-login="setup"' not in page and "only be set up from your own network" in page
    response = client_for(server).post(
        "/auth/setup", headers=OUTSIDE, json={"email": "intruder@example.com", "password": PASSWORD}
    )
    assert response.status_code == 403 and "SETUP_TOKEN" in response.json()["detail"]
    # From the server's own network it works as before.
    assert 'data-login="setup"' in httpx.get(server.base_url + "/").text
    set_up(server)


def test_claiming_to_be_on_the_network_through_a_proxy_doesnt_help(start_server):
    # A proxy appends the address it saw; FeedStash goes by that one, not by what the visitor wrote before it.
    server = start_server(DEV_LOGIN="false")
    spoofed = {"X-Forwarded-For": "192.168.1.5, 93.184.216.34"}
    response = client_for(server).post(
        "/auth/setup", headers=spoofed, json={"email": "intruder@example.com", "password": PASSWORD}
    )
    assert response.status_code == 403


def test_setup_token_allows_setup_from_anywhere(start_server):
    server = start_server(DEV_LOGIN="false", SETUP_TOKEN="only-the-owner-knows")
    page = httpx.get(server.base_url + "/", headers=OUTSIDE).text
    assert 'name="setup_token"' in page
    client = client_for(server)
    body = {"email": "owner@example.com", "name": "Owner", "password": PASSWORD}
    assert client.post("/auth/setup", headers=OUTSIDE, json=body).status_code == 403
    assert client.post("/auth/setup", headers=OUTSIDE, json={**body, "setup_token": "guess"}).status_code == 403
    assert client.post(
        "/auth/setup", headers=OUTSIDE, json={**body, "setup_token": "only-the-owner-knows"}
    ).status_code == 200
    assert client.get("/api/me").json()["is_admin"]


def test_trusting_every_proxy_means_setup_needs_the_token(start_server):
    # With FORWARDED_ALLOW_IPS=* anyone can claim any address, so FeedStash can't tell who's on the network.
    server = start_server(DEV_LOGIN="false", FORWARDED_ALLOW_IPS="*")
    response = client_for(server).post("/auth/setup", json={"email": "owner@example.com", "password": PASSWORD})
    assert response.status_code == 403
    assert "FORWARDED_ALLOW_IPS is *" in server.log_path.read_text(errors="replace")


# ------------------------------------------------------------------ sessions


def signed_in(server, password: str = PASSWORD) -> httpx.Client:
    client = client_for(server)
    assert client.post("/auth/password", json={"email": "owner@example.com", "password": password}).status_code == 200
    return client


def test_changing_your_password_signs_out_your_other_browsers(start_server):
    server = start_server(DEV_LOGIN="false")
    laptop = set_up(server)
    phone = signed_in(server)
    response = laptop.post("/api/account/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert response.status_code == 200
    assert laptop.get("/api/tree").status_code == 200  # the browser that changed it stays signed in
    assert phone.get("/api/tree").status_code == 401
    assert signed_in(server, NEW_PASSWORD).get("/api/tree").status_code == 200


def test_signing_out_other_browsers(start_server):
    server = start_server(DEV_LOGIN="false")
    laptop = set_up(server)
    phone = signed_in(server)
    token = laptop.post("/api/tokens", json={"clientName": "phone app"}).json()["token"]
    assert laptop.post("/api/account/sign-out-others").status_code == 200
    assert laptop.get("/api/tree").status_code == 200
    assert phone.get("/api/tree").status_code == 401
    # Apps with a token are separate and stay connected.
    assert httpx.get(server.base_url + "/api/tree", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    # It's a web-app action, not something a token can do.
    assert httpx.post(
        server.base_url + "/api/account/sign-out-others", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403


def test_an_admin_resetting_a_password_signs_that_account_out(start_server):
    server = start_server(DEV_LOGIN="false")
    admin = set_up(server)
    created = admin.post("/api/accounts", json={"email": "kid@example.com", "password": PASSWORD}).json()
    kid = client_for(server)
    assert kid.post("/auth/password", json={"email": "kid@example.com", "password": PASSWORD}).status_code == 200
    assert admin.patch(f"/api/accounts/{created['id']}", json={"password": NEW_PASSWORD}).status_code == 200
    assert kid.get("/api/tree").status_code == 401
    assert admin.get("/api/tree").status_code == 200


# ------------------------------------------------------------------ the mailbox password


def connect(client, **changes):
    body = {"host": "127.0.0.1", "port": 9, "username": "stash@example.com", "password": "app-password"}
    return client.put("/api/mail", json={**body, **changes})


def test_a_token_cant_touch_the_mailbox(api, server):
    assert connect(api).status_code == 200
    token = api.post("/api/tokens", json={"clientName": "extension"}).json()["token"]
    with_token = httpx.Client(
        base_url=server.base_url, headers={"Authorization": f"Bearer {token}", **CSRF_HEADERS}, timeout=30
    )
    assert with_token.put("/api/mail", json={"host": "evil.example", "username": "x"}).status_code == 403
    assert with_token.post("/api/mail/test").status_code == 403
    assert with_token.get("/api/mail").status_code == 403
    assert api.get("/api/mail").json()["host"] == "127.0.0.1"


def test_a_new_mail_server_needs_the_password_again(api):
    assert connect(api).status_code == 200
    moved = connect(api, host="mail.example.com", password="")
    assert moved.status_code == 400 and "again" in moved.json()["detail"]
    assert connect(api, username="other@example.com", password="").status_code == 400
    assert connect(api, port=1993, password="").status_code == 400
    assert connect(api, folder="Archive", password="").status_code == 200  # same server: the saved one is kept
    assert connect(api, host="mail.example.com", password="new-app-password").status_code == 200
