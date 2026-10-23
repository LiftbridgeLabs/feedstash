"""Tags: the list with counts, and renaming or merging one across every item."""


def save(api, title, tags):
    response = api.post("/api/items", json={"type": "snippet", "title": title, "content": title, "tags": tags})
    assert response.status_code == 201, response.text
    return response.json()


def test_rename_and_merge_tags(api):
    save(api, "One", ["vibes", "code"])
    save(api, "Two", ["vibing"])
    save(api, "Three", ["coding"])

    renamed = api.post("/api/tags/rename", json={"name": "vibes", "newName": "vibe"})
    assert renamed.status_code == 200 and renamed.json() == {"name": "vibe", "items": 1, "merged": False}
    merged = api.post("/api/tags/rename", json={"name": "#vibing", "newName": "vibe"}).json()
    assert merged == {"name": "vibe", "items": 1, "merged": True}
    api.post("/api/tags/rename", json={"name": "coding", "newName": "code"})

    assert {t["name"]: t["count"] for t in api.get("/api/tags").json()} == {"vibe": 2, "code": 2}
    assert [i["title"] for i in api.get("/api/items", params={"tag": "vibe"}).json()] == ["Two", "One"]


def test_renaming_a_missing_tag_says_so(api):
    response = api.post("/api/tags/rename", json={"name": "nope", "newName": "yes"})
    assert response.status_code == 404 and "#nope" in response.json()["detail"]


def test_merge_several_tags(api):
    save(api, "One", ["vibes"])
    save(api, "Two", ["vibing", "vibe"])
    merged = api.post("/api/tags/merge", json={"names": ["vibes", "vibing", "vibe"], "into": "vibe"})
    assert merged.status_code == 200 and merged.json() == {"name": "vibe", "items": 2, "merged": 2}
    assert {t["name"]: t["count"] for t in api.get("/api/tags").json()} == {"vibe": 2}


def test_delete_a_tag_from_every_item(api):
    keep = save(api, "Keep", ["recipes", "dinner"])
    only = save(api, "Only", ["recipes"])
    api.patch(f"/api/items/{only['id']}", json={"archived": True})  # archived items lose it too
    folder = api.post("/api/stash/folders", json={"name": "Kitchen"}).json()
    lists = {
        "just": api.post("/api/stash/lists", json={"name": "Recipes", "tag": "recipes"}).json(),
        "more": api.post("/api/stash/lists", json={"name": "Kitchen recipes", "tag": "recipes",
                                                   "folderId": folder["id"]}).json(),
    }
    rules = {
        "just": api.post("/api/stash/rules", json={"field": "title", "value": "soup", "addTag": "recipes"}).json(),
        "more": api.post("/api/stash/rules", json={"field": "title", "value": "stew", "addTag": "recipes",
                                                   "folderId": folder["id"]}).json(),
    }

    deleted = api.post("/api/tags/delete", json={"names": ["#recipes"]})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"items": 2, "tags": 1, "lists": 1, "rules": 1}
    assert {t["name"] for t in api.get("/api/tags").json()} == {"dinner"}
    assert api.get(f"/api/items/{keep['id']}").json()["tags"] == ["dinner"]
    assert api.get(f"/api/items/{only['id']}").json()["tags"] == []
    # The list and rule that did nothing else are gone; the ones that do more stop using the tag.
    remaining_lists = {l["id"]: l for l in api.get("/api/stash/lists").json()}
    assert lists["just"]["id"] not in remaining_lists
    assert remaining_lists[lists["more"]["id"]]["tag"] is None
    remaining_rules = {r["id"]: r for r in api.get("/api/stash/rules").json()}
    assert rules["just"]["id"] not in remaining_rules
    assert remaining_rules[rules["more"]["id"]]["addTag"] is None

    # A tag that doesn't exist, named alongside one that does, leaves lists and rules that mention it alone.
    save(api, "Three", ["soup"])
    planned = api.post("/api/stash/lists", json={"name": "Planned", "tag": "planned"}).json()
    assert api.post("/api/tags/delete", json={"names": ["soup", "planned"]}).json()["lists"] == 0
    assert planned["id"] in {l["id"] for l in api.get("/api/stash/lists").json()}

    assert api.post("/api/tags/delete", json={"names": ["recipes"]}).status_code == 404
    assert api.post("/api/tags/delete", json={"names": [" "]}).status_code == 400
