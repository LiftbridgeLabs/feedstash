def test_importing_saved_links_keeps_dates_tags_and_destinations(api):
    assert api.post("/api/items", json={"type": "link", "url": "https://example.com/already", "title": "Mine"}).status_code == 201
    links = [
        {"url": "https://example.com/reef", "title": "Best reefs", "saved_at": 1616726873, "tags": ["Diving"]},
        {"url": "https://example.com/gear", "title": "Dive gear", "tags": ["diving"], "reviewed": True},
        {"url": "https://example.com/old", "title": "Old news", "saved_at": 1392772835, "archived": True},
        {"url": "https://example.com/already", "title": "Saved before"},
        {"url": "https://example.com/reef", "title": "Same link again"},
        {"url": "javascript:alert(1)", "title": "Not a web link"},
    ]
    response = api.post("/api/items/import", json={"links": links})
    assert response.status_code == 200, response.text
    assert response.json() == {"added": 3, "already_saved": 2, "invalid": 1}

    inbox = api.get("/api/items", params={"reviewed": "false"}).json()
    assert [item["title"] for item in inbox] == ["Mine", "Best reefs"]  # newest first, by original save date
    reef = inbox[1]
    assert reef["createdAt"] == "2021-03-26T02:47:53.000Z"
    assert (reef["tags"], reef["source"], reef["type"]) == (["diving"], "import", "link")

    assert [item["title"] for item in api.get("/api/items", params={"reviewed": "true"}).json()] == ["Dive gear"]
    archived = api.get("/api/items", params={"archived": "true"}).json()
    assert [(item["title"], item["reviewed"]) for item in archived] == [("Old news", True)]
    assert api.get("/api/tags").json() == [{"name": "diving", "count": 2}]

    assert api.post("/api/items/import", json={"links": links}).json()["added"] == 0  # running it again adds nothing
    too_many = api.post("/api/items/import", json={"links": [{"url": "https://x.example.com"}] * 2001})
    assert too_many.status_code == 400
