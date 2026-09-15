def titles(api, **params) -> list[str]:
    return [article["title"] for article in api.get("/api/articles", params=params).json()["articles"]]


def test_search_feed_articles_by_their_text_including_read_ones(api, subscriptions):
    assert titles(api, scope="all", q="atom body 7", unread_only="false") == ["Atom post 7"]
    # Stemmed: "paragraphs" finds every "Paragraph for story N" in the Tech feed.
    assert len(titles(api, scope="feed", id=subscriptions.tech["id"], q="paragraphs", unread_only="false")) == 15
    assert titles(api, scope="folder", id=subscriptions.blogs_folder["id"], q="paragraphs", unread_only="false") == []
    assert titles(api, scope="all", q="%%") == []

    api.post("/api/mark-read", json={"scope": "all"})
    assert titles(api, scope="all", q="atom body 7", unread_only="false") == ["Atom post 7"]


def test_search_the_stash_by_tags_and_words_in_any_form(api):
    tagged = api.post("/api/items", json={"type": "snippet", "content": "Gear list for the trip", "tags": ["scuba"]}).json()
    api.post("/api/items", json={"type": "snippet", "content": "Groceries"})
    assert [item["id"] for item in api.get("/api/items", params={"q": "scuba"}).json()] == [tagged["id"]]
    assert [item["id"] for item in api.get("/api/items", params={"q": "trips"}).json()] == [tagged["id"]]
