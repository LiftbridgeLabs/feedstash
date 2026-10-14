"""Admins are shown what changed after an update, once; other people never are."""

import httpx

from conftest import CSRF_HEADERS

PASSWORD = "correct horse battery"


def client_for(server) -> httpx.Client:
    return httpx.Client(base_url=server.base_url, headers=CSRF_HEADERS, timeout=30)


def sign_in(server, email: str, password: str = PASSWORD) -> httpx.Client:
    client = client_for(server)
    assert client.post("/auth/password", json={"email": email, "password": password}).status_code == 200
    return client


def test_after_an_update_the_admin_sees_its_notes_once(start_server, tmp_path):
    db_path = tmp_path / "updates.db"
    first = start_server(db_path=db_path, DEV_LOGIN="false", FEEDSTASH_VERSION="0.6.0")
    admin = client_for(first)
    setup = admin.post("/auth/setup", json={"email": "owner@example.com", "name": "Owner", "password": PASSWORD})
    assert setup.status_code == 200, setup.text
    # A new server has nothing to announce.
    fresh = admin.get("/api/admin/updates").json()
    assert fresh["current"] == "0.6.0" and fresh["unseen"] == [] and fresh["latest"] is None
    assert admin.post("/api/accounts", json={"email": "kid@example.com", "password": "kid password"}).status_code == 201
    first.stop()

    updated = start_server(db_path=db_path, DEV_LOGIN="false", FEEDSTASH_VERSION="0.6.1")
    admin = sign_in(updated, "owner@example.com")
    notes = admin.get("/api/admin/updates").json()
    assert [release["version"] for release in notes["unseen"]] == ["0.6.1"]
    assert notes["unseen"][0]["url"].endswith("/releases/tag/v0.6.1")
    assert notes["unseen"][0]["sections"][0]["title"] == "New"
    assert notes["unseen"][0]["sections"][0]["items"]

    assert admin.post("/api/admin/updates/seen").status_code == 200
    assert admin.get("/api/admin/updates").json()["unseen"] == []

    kid = sign_in(updated, "kid@example.com", "kid password")
    assert kid.get("/api/admin/updates").status_code == 403
    assert kid.post("/api/admin/updates/seen").status_code == 403


def test_a_development_build_has_no_notes(start_server):
    api = start_server().login()
    info = api.get("/api/admin/updates").json()
    assert info["current"] == "dev" and info["unseen"] == [] and info["latest"] is None
