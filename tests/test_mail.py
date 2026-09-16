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


def test_email_can_say_its_folder_and_tags(api):
    """Both email paths post here, so the markers are read on the way in."""
    saved = api.post("/api/items", json={
        "type": "email", "source": "email", "title": "Deck plans $Backyard #diy",
        "content": "non wood options\n\n#spring\n",
    }).json()
    assert saved["title"] == "Deck plans"
    assert saved["tags"] == ["diy", "spring"]
    assert saved["content"] == "non wood options"
    folders = api.get("/api/stash/folders").json()
    assert [f["name"] for f in folders] == ["Backyard"]
    assert saved["folderId"] == folders[0]["id"]

    # A second mail goes to the same folder rather than making another.
    again = api.post("/api/items", json={"type": "email", "source": "email", "title": "Edging $backyard"}).json()
    assert again["folderId"] == folders[0]["id"]
    assert len(api.get("/api/stash/folders").json()) == 1

    # Anything else keeps its text: only mail is read for markers.
    web = api.post("/api/items", json={"type": "link", "url": "https://example.com/x", "title": "$5 off #deal"}).json()
    assert web["title"] == "$5 off #deal" and web["folderId"] is None and web["tags"] == []


def test_a_client_can_name_the_folder_it_wants(api):
    saved = api.post("/api/items", json={
        "type": "link", "url": "https://example.com/plan", "folder": "Reading list"
    }).json()
    assert [f["name"] for f in api.get("/api/stash/folders").json()] == ["Reading list"]
    assert saved["folderId"] is not None


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
