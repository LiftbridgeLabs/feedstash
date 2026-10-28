import sqlite3

from conftest import CSRF_HEADERS
from test_auth import PASSWORD, client_for, set_up


def token_of(invite: dict) -> str:
    return invite["links"][0].split("#", 1)[1]


def test_an_invite_link_makes_one_ordinary_account_and_then_stops_working(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="http://localhost:9,https://reader.example.com")
    admin = set_up(server)
    invite = admin.post("/api/invites", json={"days": 7}).json()
    assert invite["links"][0].startswith("https://reader.example.com/invite#")  # the outside address first
    assert invite["links"][1].startswith("http://localhost:9/invite#")
    assert invite["email"] is None and invite["created_by"] == "Owner"
    assert [i["id"] for i in admin.get("/api/invites").json()] == [invite["id"]]
    assert admin.get("/api/invites").json()[0]["links"] == []  # the links are only shown when they're made

    assert client_for(server).get("/invite").status_code == 200
    guest = client_for(server)
    assert guest.post("/auth/invite/check", json={"token": token_of(invite)}).json() == {
        "usable": True, "email": None, "detail": None}
    joined = guest.post("/auth/invite", json={
        "token": token_of(invite), "email": "Guest@Example.com", "name": "Guest", "password": PASSWORD,
    })
    assert joined.status_code == 200, joined.text
    me = guest.get("/api/me").json()
    assert me["email"] == "guest@example.com" and me["is_admin"] is False

    again = client_for(server).post("/auth/invite", json={
        "token": token_of(invite), "email": "second@example.com", "password": PASSWORD,
    })
    assert again.status_code == 404 and "has been used" in again.json()["detail"]
    used = client_for(server).post("/auth/invite/check", json={"token": token_of(invite)}).json()
    assert used["usable"] is False and "has been used" in used["detail"]
    assert admin.get("/api/invites").json() == []
    # A member can't hand out invites.
    assert guest.post("/api/invites", json={"days": 7}).status_code == 403
    assert guest.get("/api/invites").status_code == 403


def test_an_invite_for_one_address_canceled_or_expired_invites_and_the_allowed_list(start_server):
    server = start_server(DEV_LOGIN="false", ALLOWED_DOMAINS="example.com")
    admin = set_up(server)
    for_ann = admin.post("/api/invites", json={"email": " Ann@Example.com ", "days": 1}).json()
    assert for_ann["email"] == "ann@example.com"
    guest = client_for(server)
    assert guest.post("/auth/invite/check", json={"token": token_of(for_ann)}).json()["email"] == "ann@example.com"
    wrong = guest.post("/auth/invite", json={"token": token_of(for_ann), "email": "bob@example.com", "password": PASSWORD})
    assert wrong.status_code == 400 and "ann@example.com" in wrong.json()["detail"]

    anyone = admin.post("/api/invites", json={"days": 30}).json()
    outside = guest.post("/auth/invite", json={"token": token_of(anyone), "email": "eve@elsewhere.org", "password": PASSWORD})
    assert outside.status_code == 403  # the allowed list still applies
    assert admin.delete(f"/api/invites/{anyone['id']}").json() == {"ok": True}
    assert guest.post("/auth/invite/check", json={"token": token_of(anyone)}).json()["usable"] is False

    with sqlite3.connect(server.db_path) as db:
        db.execute("UPDATE invites SET expires_at = 1 WHERE id = ?", (for_ann["id"],))
    expired = guest.post("/auth/invite", json={"token": token_of(for_ann), "email": "ann@example.com", "password": PASSWORD})
    assert expired.status_code == 404
    assert admin.post("/api/invites", json={"days": 3}).status_code == 400
    assert admin.post("/api/invites", json={"email": "ann@@example.com", "days": 7}).status_code == 400
    assert guest.post("/auth/invite", json={"token": "made-up", "email": "x@example.com", "password": PASSWORD},
                      headers=CSRF_HEADERS).status_code == 404


def test_no_invites_without_password_sign_in(start_server):
    server = start_server(PASSWORD_LOGIN="false")
    api = server.login()  # the dev login
    refused = api.post("/api/invites", json={"days": 7})
    assert refused.status_code == 409 and "password sign-in is turned off" in refused.json()["detail"]
    assert client_for(server).post("/auth/invite/check", json={"token": "x"}).status_code == 404
