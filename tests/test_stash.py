import hashlib
import sqlite3

import httpx

from support.images import PNG


def create(api, **fields):
    return api.post("/api/items", json=fields)


def test_capture_list_filter_and_search(api):
    link = create(api, type="link", url="https://example.com/a", title="Alpha article", tags="reading, Later")
    assert link.status_code == 201, link.text
    body = link.json()
    assert body["tags"] == ["later", "reading"]
    assert body["source"] == "web"
    assert body["reviewed"] is False and body["archived"] is False
    create(api, type="snippet", content="100% pure snippet_text", tags=["code"])
    create(api, type="email", title="Newsletter", content="Hello", source="email")

    assert [i["type"] for i in api.get("/api/items").json()] == ["email", "snippet", "link"]
    assert [i["title"] for i in api.get("/api/items", params={"type": "link"}).json()] == ["Alpha article"]
    assert len(api.get("/api/items", params={"tag": "READING"}).json()) == 1
    # LIKE wildcards in a search are matched literally.
    assert len(api.get("/api/items", params={"q": "100%"}).json()) == 1
    assert len(api.get("/api/items", params={"q": "_"}).json()) == 1
    assert len(api.get("/api/items", params={"limit": 2}).json()) == 2
    assert len(api.get("/api/items", params={"limit": 2, "offset": 2}).json()) == 1


def test_review_archive_edit_and_delete(api):
    item = create(api, type="link", url="https://example.com/x").json()
    updated = api.patch(f"/api/items/{item['id']}", json={"reviewed": True, "title": "Renamed", "tags": "a,b"}).json()
    assert updated["reviewed"] and updated["title"] == "Renamed" and updated["tags"] == ["a", "b"]
    assert api.get("/api/items", params={"reviewed": "false"}).json() == []

    api.patch(f"/api/items/{item['id']}", json={"archived": True})
    assert api.get("/api/items").json() == []
    assert [i["id"] for i in api.get("/api/items", params={"archived": "true"}).json()] == [item["id"]]

    cleared = api.patch(f"/api/items/{item['id']}", json={"title": None}).json()
    assert cleared["title"] is None and cleared["reviewed"]

    assert api.delete(f"/api/items/{item['id']}").status_code == 204
    assert api.get(f"/api/items/{item['id']}").status_code == 404
    assert api.patch("/api/items/999999", json={"reviewed": True}).status_code == 404


def test_tag_counts_skip_archived_items(api):
    first = create(api, type="link", url="https://a.example.com", tags="shared,only-a").json()
    create(api, type="link", url="https://b.example.com", tags="shared")
    assert api.get("/api/tags").json() == [{"name": "shared", "count": 2}, {"name": "only-a", "count": 1}]
    api.patch(f"/api/items/{first['id']}", json={"archived": True})
    assert api.get("/api/tags").json() == [{"name": "shared", "count": 1}]


def test_an_item_can_hold_several_labeled_links(api):
    note = api.post("/api/items", data={
        "type": "snippet", "content": "Launch research",
        "links": '[{"url": "https://a.example.com", "label": "A"}, "https://b.example.com"]',
    })
    assert note.status_code == 201, note.text
    body = note.json()
    assert body["url"] == "https://a.example.com"
    assert [(link["url"], link["label"]) for link in body["links"]] == [
        ("https://a.example.com", "A"), ("https://b.example.com", None),
    ]
    assert [i["id"] for i in api.get("/api/items", params={"q": "b.example"}).json()] == [body["id"]]

    # `url` alone swaps the primary link; `links` replaces the whole list.
    swapped = api.patch(f"/api/items/{body['id']}", json={"url": "https://c.example.com"}).json()
    assert [link["url"] for link in swapped["links"]] == ["https://c.example.com", "https://b.example.com"]
    replaced = api.patch(f"/api/items/{body['id']}", json={"links": "https://d.example.com\nhttps://e.example.com"}).json()
    assert replaced["url"] == "https://d.example.com" and len(replaced["links"]) == 2
    emptied = api.patch(f"/api/items/{body['id']}", json={"links": []}).json()
    assert emptied["url"] is None and emptied["links"] == []

    assert create(api, type="link", links=["https://only.example.com"]).json()["url"] == "https://only.example.com"
    assert create(api, type="snippet", links=["https://x.example.com"]).status_code == 201  # notes can be just links


def test_screenshot_is_stored_served_as_an_image_and_deleted_with_its_item(api):
    response = api.post("/api/items", data={"type": "screenshot", "title": "Shot"}, files={"image": ("s.png", PNG, "image/png")})
    assert response.status_code == 201, response.text
    path = response.json()["imagePath"]
    assert path.startswith("/uploads/") and path.endswith(".png")

    image = httpx.get(str(api.base_url.join(path)))  # no sign-in: the random name is the key
    assert image.status_code == 200
    assert image.content == PNG
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"

    api.delete(f"/api/items/{response.json()['id']}")
    assert httpx.get(str(api.base_url.join(path))).status_code == 404
    assert httpx.get(str(api.base_url.join("/uploads/..%2Fsecret.key"))).status_code == 404


def test_invalid_captures_are_rejected_with_readable_errors(api):
    cases = [
        ({"json": {"type": "video"}}, "type must be one of"),
        ({"json": {"type": "link"}}, "url"),
        ({"json": {"type": "snippet", "content": "   "}}, "content"),
        ({"data": {"type": "screenshot"}}, "image"),
        ({"data": {"type": "screenshot"}, "files": {"image": ("x.png", b"<html><script>alert(1)</script>", "image/png")}}, "PNG"),
    ]
    for kwargs, message in cases:
        response = api.post("/api/items", **kwargs)
        assert response.status_code == 400, (kwargs, response.text)
        assert message in response.json()["error"]
    assert api.post("/api/items", content=b"not json", headers={"content-type": "application/json"}).status_code == 400


def test_stash_an_article_from_a_feed(api, subscriptions):
    article = api.get("/api/articles", params={"scope": "feed", "id": subscriptions.tech["id"], "limit": 1}).json()["articles"][0]
    first = api.post(f"/api/articles/{article['id']}/stash").json()
    assert first["created"]
    assert first["item"]["url"] == article["url"] and first["item"]["source"] == "feed"
    again = api.post(f"/api/articles/{article['id']}/stash").json()
    assert not again["created"] and again["item"]["id"] == first["item"]["id"]
    assert api.post("/api/articles/999999/stash").status_code == 404


def test_summary_counts_inbox_types_and_archive(api):
    link = create(api, type="link", url="https://example.com/l").json()
    create(api, type="snippet", content="one")
    reviewed = create(api, type="snippet", content="two").json()
    api.patch(f"/api/items/{reviewed['id']}", json={"reviewed": True})
    api.patch(f"/api/items/{link['id']}", json={"archived": True})
    assert api.get("/api/stash/summary").json() == {
        "inbox": 1, "total": 2, "archived": 1, "by_type": {"link": 0, "snippet": 2, "screenshot": 0, "email": 0},
        "folders": [], "lists": [],
    }


def test_each_user_only_sees_their_own_stash(api, server):
    mine = create(api, type="link", url="https://mine.example.com").json()
    secret = "another-users-token-value"
    with sqlite3.connect(server.db_path) as db:
        other = db.execute("INSERT INTO users (sub, email, created_at) VALUES ('other', 'other@example.com', 0)").lastrowid
        db.execute(
            "INSERT INTO api_tokens (user_id, token_hash, hint, client_name, created_at) VALUES (?, ?, ?, 'test', 0)",
            (other, hashlib.sha256(secret.encode()).hexdigest(), secret[-4:]),
        )
    theirs = httpx.Client(base_url=server.base_url, headers={"Authorization": f"Bearer {secret}"})
    assert theirs.get("/api/items").json() == []
    assert theirs.get(f"/api/items/{mine['id']}").status_code == 404
    assert theirs.delete(f"/api/items/{mine['id']}").status_code == 404
    assert theirs.post("/api/items", json={"type": "snippet", "content": "private"}).status_code == 201
    assert [i["id"] for i in api.get("/api/items").json()] == [mine["id"]]


def test_links_that_could_run_code_are_refused(api):
    for url in ("javascript:alert(1)", " JavaScript:alert(1)", "java\tscript:alert(1)", "data:text/html,<b>x</b>",
                "vbscript:x", "file:///etc/passwd"):
        response = api.post("/api/items", json={"type": "link", "url": url})
        assert response.status_code == 400, url
        response = api.post("/api/items", json={"type": "snippet", "content": "x", "links": [url]})
        assert response.status_code == 400, url
    item = api.post("/api/items", json={"type": "snippet", "content": "x", "links": ["mailto:me@example.com"]}).json()
    assert api.patch(f"/api/items/{item['id']}", json={"url": "javascript:alert(1)"}).status_code == 400
    # Web addresses and app links are kept.
    assert [link["url"] for link in item["links"]] == ["mailto:me@example.com"]
