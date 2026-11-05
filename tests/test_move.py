"""Moving an account to another FeedStash: Download everything (GET /api/account/export) on one server, bring it in
(POST /api/account/import) on another."""

import io
import json
import sqlite3
import zipfile

from support.images import PNG
from test_auth import PASSWORD, client_for, set_up


def fill(api, feed_server: str) -> dict:
    """An account with a bit of everything."""
    folder = api.post("/api/folders", json={"name": "Science"}).json()
    feed = api.post("/api/feeds", json={"url": f"{feed_server}/tech.xml", "folder_id": folder["id"]}).json()
    api.patch(f"/api/feeds/{feed['id']}", json={"open_website": True})
    articles = api.get("/api/articles", params={"scope": "feed", "id": feed["id"]}).json()["articles"]
    api.post("/api/articles/mark", json={"ids": [articles[0]["id"]], "read": True})
    api.post("/api/articles/star", json={"ids": [articles[1]["id"]], "starred": True})
    box = api.post("/api/stash/folders", json={"name": "Recipes"}).json()
    api.post("/api/items", json={"type": "link", "title": "Bread", "url": "https://example.com/bread",
                                 "tags": ["baking", "weekend"], "folderId": box["id"]})
    api.post("/api/items", data={"type": "screenshot", "title": "Shot"}, files={"image": ("s.png", PNG, "image/png")})
    api.post("/api/items", json={"type": "snippet", "title": "A note", "content": "Remember the milk"})
    api.post("/api/stash/lists", json={"name": "Baking", "tag": "baking"})
    api.post("/api/stash/rules", json={"field": "title", "value": "Bread", "addTag": "web"})
    api.post("/api/muted-words", json={"phrase": "crypto", "folder_id": folder["id"]})
    api.patch("/api/account", json={"read_retention_days": 7})
    return {"feed": feed, "read": articles[0]["guid"] if "guid" in articles[0] else articles[0]["title"],
            "starred": articles[1]["title"]}


def export(api) -> bytes:
    response = api.get("/api/account/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    return response.content


def bring_in(api, data: bytes, name: str = "export.zip"):
    return api.post("/api/account/import", files={"file": (name, data, "application/zip")})


def test_everything_moves_to_another_server_and_bringing_it_in_twice_doubles_nothing(start_server, feed_server):
    old, new = start_server(), start_server()
    source, target = old.login(), new.login()
    filled = fill(source, feed_server)
    data = export(source)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        account = json.loads(archive.read("account.json"))
    assert account["format"] == "feedstash-account" and account["version"] == 1
    assert sum(name.startswith("pictures/") for name in names) == 1
    assert "password" not in json.dumps(account) and "token" not in json.dumps(account["account"])

    counts = bring_in(target, data)
    assert counts.status_code == 200, counts.text
    first = counts.json()
    assert first["feeds"] == 1 and first["folders"] == 1 and first["items"] == 3 and first["stash_folders"] == 1
    assert first["articles"] > 2 and first["smart_lists"] == 1 and first["stash_rules"] == 1
    assert first["muted_words"] == 1 and first["skipped"] == []

    tree = target.get("/api/tree").json()
    [feed] = tree["feeds"]
    assert feed["url"] == filled["feed"]["url"] and feed["open_website"] is True
    assert [f["name"] for f in tree["folders"]] == ["Science"] and feed["folder_id"] == tree["folders"][0]["id"]
    starred = target.get("/api/articles", params={"scope": "starred"}).json()["articles"]
    assert [a["title"] for a in starred] == [filled["starred"]]
    assert target.get("/api/articles/ids", params={"scope": "feed", "id": feed["id"], "state": "unread"}).json()["ids"]
    items = {item["title"]: item for item in target.get("/api/items").json()}
    assert set(items) == {"Bread", "Shot", "A note"}
    assert items["Bread"]["tags"] == ["baking", "weekend"]
    assert items["A note"]["content"] == "Remember the milk"
    picture = target.get(items["Shot"]["imagePath"])
    assert picture.status_code == 200 and picture.content == PNG
    assert [l["name"] for l in target.get("/api/stash/lists").json()] == ["Baking"]
    assert target.get("/api/me").json()["read_retention_days"] == 7
    assert target.get("/api/items", params={"q": "milk"}).json()[0]["title"] == "A note"  # searchable

    again = bring_in(target, data).json()
    assert {key: value for key, value in again.items() if key != "skipped"} == dict.fromkeys(
        ["folders", "feeds", "articles", "stash_folders", "items", "smart_lists", "stash_rules", "muted_words"], 0)
    assert len(target.get("/api/items").json()) == 3
    # The second time's copy of the picture was removed again, not left behind. (Both test servers share one
    # uploads folder: the original and the first import's copy.)
    with sqlite3.connect(new.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM item_images").fetchone()[0] == 1
    assert len(list((new.db_path.parent / "uploads").iterdir())) == 2


def test_files_that_arent_exports_are_refused(start_server):
    api = start_server().login()
    not_zip = bring_in(api, b"hello", "notes.txt")
    assert not_zip.status_code == 400 and "isn't a FeedStash export" in not_zip.json()["detail"]

    def zipped(**files) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    assert bring_in(api, zipped(**{"other.json": "{}"})).status_code == 400
    assert bring_in(api, zipped(**{"account.json": "not json"})).status_code == 400
    wrong = bring_in(api, zipped(**{"account.json": json.dumps({"format": "something-else"})}))
    assert wrong.status_code == 400
    newer = bring_in(api, zipped(**{"account.json": json.dumps({"format": "feedstash-account", "version": 99})}))
    assert newer.status_code == 400 and "newer FeedStash" in newer.json()["detail"]
    assert api.post("/api/account/import", data={"x": "y"}).status_code == 400


def test_a_picture_that_isnt_an_image_is_left_out(start_server):
    api = start_server().login()
    account = {"format": "feedstash-account", "version": 1, "items": [
        {"type": "screenshot", "title": "Fake", "created_at": 1, "images": ["fakefakefakefakefake.png"]}]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("account.json", json.dumps(account))
        archive.writestr("pictures/fakefakefakefakefake.png", b"<script>alert(1)</script>")
    result = bring_in(api, buffer.getvalue()).json()
    assert result["items"] == 1 and "wasn't in the file" in result["skipped"][0]
    [item] = api.get("/api/items").json()
    assert item["imagePath"] is None


def test_an_export_holds_only_your_own_things(start_server, feed_server):
    server = start_server(DEV_LOGIN="false")
    owner = set_up(server)
    owner.post("/api/items", json={"type": "snippet", "title": "Owner's secret", "content": "only mine"})
    owner.post("/api/accounts", json={"email": "kid@example.com", "password": PASSWORD})
    kid = client_for(server)
    kid.post("/auth/password", json={"email": "kid@example.com", "password": PASSWORD})
    assert kid.post("/api/items", json={"type": "snippet", "title": "Kid's note", "content": "hi"}).status_code == 201
    with zipfile.ZipFile(io.BytesIO(export(kid))) as archive:
        account = json.loads(archive.read("account.json"))
    assert [item["title"] for item in account["items"]] == ["Kid's note"]
    assert "owner" not in json.dumps(account).lower()
