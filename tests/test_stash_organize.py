"""Stash folders, smart lists (saved searches) and rules that sort new items."""


def new_folder(api, name: str) -> dict:
    return api.post("/api/stash/folders", json={"name": name}).json()


def test_folders_hold_items_and_deleting_one_keeps_them(api):
    work = new_folder(api, "Work")
    assert work["count"] == 0
    filed = api.post("/api/items", json={"type": "link", "url": "https://example.com/spec", "folderId": work["id"]}).json()
    loose = api.post("/api/items", json={"type": "snippet", "content": "Somewhere else"}).json()
    assert filed["folderId"] == work["id"] and loose["folderId"] is None

    assert [item["id"] for item in api.get("/api/items", params={"folder": work["id"]}).json()] == [filed["id"]]
    assert api.get("/api/stash/summary").json()["folders"] == [
        {"id": work["id"], "name": "Work", "position": 0, "count": 1}
    ]

    assert api.patch(f"/api/stash/folders/{work['id']}", json={"name": "Work notes"}).json()["name"] == "Work notes"
    assert api.post("/api/stash/folders", json={"name": "work NOTES"}).status_code == 409
    assert api.patch(f"/api/items/{loose['id']}", json={"folderId": work["id"]}).json()["folderId"] == work["id"]
    assert api.patch(f"/api/items/{filed['id']}", json={"folderId": None}).json()["folderId"] is None
    assert api.post("/api/items", json={"type": "link", "url": "https://example.com/x", "folderId": 9999}).status_code == 404

    # The folder goes; what was in it stays in the stash.
    assert api.delete(f"/api/stash/folders/{work['id']}").status_code == 200
    assert api.get(f"/api/items/{loose['id']}").json()["folderId"] is None
    assert api.get("/api/stash/summary").json()["folders"] == []


def test_smart_lists_keep_a_search(api):
    reading = new_folder(api, "Reading")
    match = api.post("/api/items", json={
        "type": "link", "url": "https://example.com/reefs", "title": "Reef guide", "folderId": reading["id"]
    }).json()
    api.post("/api/items", json={"type": "link", "url": "https://example.com/bikes", "title": "Bike guide"})

    smart = api.post("/api/stash/lists", json={"name": "Reefs", "query": "reef", "folderId": reading["id"]}).json()
    assert (smart["query"], smart["folderId"], smart["type"]) == ("reef", reading["id"], None)
    assert api.get("/api/stash/summary").json()["lists"][0]["name"] == "Reefs"

    found = api.get("/api/items", params={"q": smart["query"], "folder": smart["folderId"]}).json()
    assert [item["id"] for item in found] == [match["id"]]

    assert api.patch(f"/api/stash/lists/{smart['id']}", json={"name": "Reef reading", "type": "link"}).json()["type"] == "link"
    assert api.post("/api/stash/lists", json={"name": "Anything"}).status_code == 400  # nothing to look for
    assert api.post("/api/stash/lists", json={"name": "reef READING", "query": "x"}).status_code == 409

    # A deleted folder takes its smart lists with it.
    api.delete(f"/api/stash/folders/{reading['id']}")
    assert api.get("/api/stash/lists").json() == []


def test_rules_tag_file_and_review_what_arrives(api):
    box = new_folder(api, "Blogs")
    rule = api.post("/api/stash/rules", json={
        "field": "domain", "value": "https://www.blog.example.com/posts", "addTag": "Blog",
        "folderId": box["id"], "markReviewed": True,
    }).json()
    assert rule["value"] == "blog.example.com"  # written as an address, kept as the website

    matched = api.post("/api/items", json={"type": "link", "url": "https://blog.example.com/one"}).json()
    assert matched["tags"] == ["blog"] and matched["folderId"] == box["id"] and matched["reviewed"]
    other = api.post("/api/items", json={"type": "link", "url": "https://example.com/one"}).json()
    assert other["tags"] == [] and not other["reviewed"] and other["folderId"] is None

    # A new rule only applies to what arrives next, until you run it over everything saved.
    api.post("/api/stash/rules", json={"field": "url", "value": "example.com/one", "addTag": "ones"})
    assert api.post("/api/stash/rules/apply").json()["changed"] == 2
    assert api.get(f"/api/items/{other['id']}").json()["tags"] == ["ones"]

    assert api.post("/api/stash/rules", json={"field": "domain", "value": "x.example.com"}).status_code == 400
    assert api.post("/api/stash/rules", json={"field": "nonsense", "value": "x", "archive": True}).status_code == 400
    assert api.post("/api/stash/rules", json={"field": "feed", "value": 999, "archive": True}).status_code == 400
    assert api.delete(f"/api/stash/rules/{rule['id']}").status_code == 200
    assert len(api.get("/api/stash/rules").json()) == 1


def test_a_feed_can_be_set_to_save_its_articles(api, subscriptions):
    feed_id = subscriptions.tech["id"]
    assert not api.get("/api/tree").json()["feeds"][0]["auto_stash"]
    assert api.patch(f"/api/feeds/{feed_id}", json={"auto_stash": True}).json()["auto_stash"]
    assert next(f for f in api.get("/api/tree").json()["feeds"] if f["id"] == feed_id)["auto_stash"]
    assert not api.patch(f"/api/feeds/{feed_id}", json={"auto_stash": False}).json()["auto_stash"]
