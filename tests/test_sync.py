"""The primitives a syncing client needs: which ids exist, the articles behind them, and batch state writes."""


def ids(api, **params) -> list[int]:
    return api.get("/api/articles/ids", params=params).json()["ids"]


def test_a_client_can_ask_which_ids_it_should_have(api, subscriptions):
    everything = api.get("/api/articles/ids", params={"scope": "all", "state": "all"}).json()
    unread = api.get("/api/articles/ids", params={"scope": "all"}).json()  # unread is the default
    assert len(everything["ids"]) == 75  # 15 from Tech, 60 from the Atom blog
    assert unread["ids"] == everything["ids"]  # nothing read yet
    assert everything["max_id"] == max(everything["ids"])

    # Reading some changes what's unread, but not what exists.
    api.post("/api/articles/mark", json={"ids": everything["ids"][:10], "read": True})
    assert len(ids(api, scope="all", state="all")) == 75
    assert len(ids(api, scope="all")) == 65

    # A scope narrows it, and since_id answers "what arrived after my last sync".
    tech = ids(api, scope="feed", id=subscriptions.tech["id"], state="all")
    assert len(tech) == 15
    assert ids(api, scope="all", state="all", since_id=everything["max_id"]) == []
    assert len(ids(api, scope="all", state="all", since_id=min(everything["ids"]))) == 74


def test_starring_a_batch_and_reading_it_back(api, subscriptions):
    everything = ids(api, scope="all", state="all")
    chosen = everything[:3]
    assert api.post("/api/articles/star", json={"ids": chosen, "starred": True}).json()["updated"] == 3
    assert sorted(ids(api, scope="all", state="starred")) == sorted(chosen)

    assert api.post("/api/articles/star", json={"ids": chosen[:1], "starred": False}).json()["updated"] == 1
    assert sorted(ids(api, scope="all", state="starred")) == sorted(chosen[1:])
    assert api.post("/api/articles/star", json={"ids": [], "starred": True}).json()["updated"] == 0


def test_fetching_the_articles_behind_a_list_of_ids(api, subscriptions):
    wanted = ids(api, scope="all", state="all")[:5]
    articles = api.post("/api/articles/contents", json={"ids": wanted}).json()
    assert [article["id"] for article in articles] == wanted
    assert all(article["content"] is not None for article in articles)

    # Ids that aren't yours are left out rather than refused.
    assert api.post("/api/articles/contents", json={"ids": [999999]}).json() == []
    assert api.post("/api/articles/contents", json={"ids": []}).json() == []
