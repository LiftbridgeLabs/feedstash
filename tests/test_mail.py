"""Connecting a mailbox for email-to-stash. Nothing here talks to a real mail server."""

CLOSED_PORT = 9  # discard: nothing listens, so connecting fails immediately


def connect(api, **changes):
    body = {"host": "127.0.0.1", "port": CLOSED_PORT, "username": "stash@example.com", "password": "app-password"}
    return api.put("/api/mail", json={**body, **changes})


def test_connecting_changing_and_disconnecting_a_mailbox(api):
    empty = api.get("/api/mail").json()
    assert empty["connected"] is False and empty["pollMinutes"] == 5

    saved = connect(api, allowedSenders=["Me@Example.com", "@work.example"]).json()
    assert saved["connected"] and saved["username"] == "stash@example.com"
    assert saved["allowedSenders"] == ["me@example.com", "@work.example"]
    assert "password" not in saved  # never sent back

    # The password is kept when it isn't sent again.
    changed = connect(api, password="", folder="Archive").json()
    assert changed["folder"] == "Archive" and changed["connected"]

    assert api.delete("/api/mail").status_code == 200
    assert api.get("/api/mail").json()["connected"] is False
    assert api.post("/api/mail/test").status_code == 404


def test_a_mailbox_needs_a_server_a_user_and_a_password(api):
    assert connect(api, host=" ").status_code == 400
    assert connect(api, username="").status_code == 400
    assert connect(api, password="").status_code == 400  # nothing saved yet to fall back on


def test_testing_and_checking_report_what_went_wrong(api):
    connect(api)
    check = api.post("/api/mail/test").json()
    assert check["ok"] is False and "couldn't reach" in check["error"].lower()

    now = api.post("/api/mail/check").json()
    assert now["saved"] == 0 and now["error"]

    # The failure is remembered, so Settings can show it.
    status = api.get("/api/mail").json()
    assert status["lastError"] and status["lastCheckedAt"]
