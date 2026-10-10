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


def test_the_connect_page_works_without_signing_in_and_never_holds_the_token(server):
    page = httpx.get(server.base_url + "/connect")
    assert page.status_code == 200
    assert "Open in FeedStash" in page.text and 'src="/static/connect.js"' in page.text
    assert page.headers["cache-control"] == "no-store"
