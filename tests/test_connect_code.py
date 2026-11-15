"""Connecting the phone and iPad apps by QR code: a new token, and a link the app opens to connect."""

from urllib.parse import parse_qs, urlsplit

import httpx


def test_a_connect_code_holds_the_server_and_a_working_token(api, server):
    created = api.post("/api/tokens/connect", json={}).json()
    assert created["clientName"] == "Phone or iPad"
    (code,) = created["codes"]
    assert code["server"] == server.base_url
    link = urlsplit(code["url"])
    assert f"{link.scheme}://{link.netloc}{link.path}" == server.base_url + "/connect"
    assert link.query == ""  # nothing a server would see or log
    assert parse_qs(link.fragment) == {"server": [server.base_url], "token": [created["token"]]}
    assert code["svg"].lstrip().startswith("<svg")
    # The token in it signs in like any other, and it's listed for revoking.
    me = httpx.get(server.base_url + "/api/me", headers={"Authorization": f"Bearer {created['token']}"})
    assert me.status_code == 200
    assert "Phone or iPad" in [token["clientName"] for token in api.get("/api/tokens").json()]


def test_every_configured_address_gets_a_code_this_browsers_first(start_server):
    server = start_server(BASE_URL="https://feeds.example.com,{server}")
    client = httpx.Client(base_url=server.base_url, headers={"X-Requested-With": "reader"}, timeout=30)
    client.get("/auth/login")
    servers = [code["server"] for code in client.post("/api/tokens/connect", json={}).json()["codes"]]
    assert servers == [server.base_url, "https://feeds.example.com"]


def test_a_token_cant_make_connect_codes(api, server):
    token = api.post("/api/tokens", json={"clientName": "extension"}).json()["token"]
    response = httpx.post(
        server.base_url + "/api/tokens/connect", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_the_phone_app_connects_a_second_device_with_the_accounts_password(start_server):
    server = start_server(DEV_LOGIN="false")
    owner = httpx.Client(base_url=server.base_url, headers={"X-Requested-With": "reader"}, timeout=30)
    assert owner.post("/auth/setup", json={"email": "owner@example.com", "password": "correct horse battery"}).status_code == 200
    first = owner.post("/api/tokens", json={"clientName": "iPhone"}).json()["token"]
    phone = httpx.Client(base_url=server.base_url, headers={"Authorization": f"Bearer {first}"}, timeout=30)

    wrong = phone.post("/api/tokens/connect-device", json={"current_password": "nope", "clientName": "iPad"})
    assert wrong.status_code == 400 and "current password" in wrong.json()["detail"]
    made = phone.post("/api/tokens/connect-device", json={"current_password": "correct horse battery", "clientName": "iPad"})
    assert made.status_code == 201, made.text
    (code,) = made.json()["codes"]
    assert parse_qs(urlsplit(code["url"]).fragment) == {"server": [server.base_url], "token": [made.json()["token"]]}
    second = httpx.get(server.base_url + "/api/me", headers={"Authorization": f"Bearer {made.json()['token']}"})
    assert second.status_code == 200 and second.json()["email"] == "owner@example.com"
    assert "iPad" in [token["clientName"] for token in owner.get("/api/tokens").json()]

    # A token can't be used to guess the password: with the wrong one above, the tenth miss is the last.
    codes = [phone.post("/api/tokens/connect-device", json={"current_password": f"guess {n}"}).status_code for n in range(10)]
    assert codes == [400] * 9 + [429]


def test_the_connect_page_works_without_signing_in_and_never_holds_the_token(server):
    page = httpx.get(server.base_url + "/connect")
    assert page.status_code == 200
    assert "Open in FeedStash" in page.text and 'src="/static/connect.js"' in page.text
    assert page.headers["cache-control"] == "no-store"
