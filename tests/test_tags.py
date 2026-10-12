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
