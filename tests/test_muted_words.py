from conftest import unread_count


def test_muting_a_word_with_catch_up_and_undo(api, subscriptions):
    tech = subscriptions.tech["id"]
    before = unread_count(api, tech)
    added = api.post("/api/muted-words", json={"phrase": "  tech   STORY 3 ", "mark_unread_read": True})
    assert added.status_code == 201
    body = added.json()
    assert body["word"] == {"id": body["word"]["id"], "phrase": "tech STORY 3", "title_only": True,
                            "folder_id": None, "feed_id": None}
    assert body["marked"] == 1  # "Tech story 3 (…)", not story 13
    assert unread_count(api, tech) == before - 1
    undo = api.post("/api/mark-read/undo", json={"scope": "all", "batch": body["batch"]}).json()
    assert undo == {"restored": 1}

    in_feed = api.post("/api/muted-words", json={"phrase": "paragraph", "title_only": False, "feed_id": tech}).json()
    assert in_feed["marked"] == 0  # not asked to catch up
    assert [w["phrase"] for w in api.get("/api/muted-words").json()] == ["paragraph", "tech STORY 3"]

    assert api.delete(f"/api/muted-words/{in_feed['word']['id']}").json() == {"ok": True}
    assert api.delete(f"/api/muted-words/{in_feed['word']['id']}").status_code == 404
    assert api.post("/api/muted-words", json={"phrase": "   "}).status_code == 400
    assert api.post("/api/muted-words", json={"phrase": "x", "feed_id": 999999}).status_code == 404
