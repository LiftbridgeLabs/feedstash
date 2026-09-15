def test_follow_an_rss_feed_into_a_folder(api, feed_server):
    folder = api.post("/api/folders", json={"name": "Tech"}).json()
    feed = api.post("/api/feeds", json={"url": f"{feed_server}/tech.xml", "folder_id": folder["id"]}).json()
    assert feed["title"] == "Test Tech"
    assert feed["unread"] == 15
    assert feed["folder_id"] == folder["id"]


def test_discovers_the_feed_behind_a_web_page(api, feed_server):
    feed = api.post("/api/feeds", json={"url": f"{feed_server}/site.html", "folder_name": "Blogs"}).json()
    assert feed["url"] == f"{feed_server}/posts.atom"
    assert feed["unread"] == 60
    assert [f["name"] for f in api.get("/api/tree").json()["folders"]] == ["Blogs"]


def test_follow_rejects_duplicates_bad_urls_and_non_feeds(api, feed_server):
    assert api.post("/api/feeds", json={"url": f"{feed_server}/tech.xml"}).status_code == 200
    duplicate = api.post("/api/feeds", json={"url": f"{feed_server}/tech.xml"})
    assert duplicate.status_code == 409
    assert isinstance(duplicate.json()["detail"], str)
    assert api.post("/api/feeds", json={"url": "ftp://example.com/feed"}).status_code == 400
    missing = api.post("/api/feeds", json={"url": f"{feed_server}/nothing-here"})
    assert missing.status_code == 400
    assert "404" in missing.json()["detail"]
    page_without_feed = api.post("/api/feeds", json={"url": f"{feed_server}/plain.html"})
    assert page_without_feed.status_code == 400
    assert "couldn't find" in page_without_feed.json()["detail"].lower()


def test_change_a_feeds_address(api, subscriptions):
    tech, atom, feeds = subscriptions.tech, subscriptions.atom, subscriptions.feed_server
    # The new address is fetched first: a page with no feed is refused, and one someone already follows conflicts.
    assert api.patch(f"/api/feeds/{tech['id']}", json={"url": f"{feeds}/plain.html"}).status_code == 400
    assert api.patch(f"/api/feeds/{tech['id']}", json={"url": f"{feeds}/site.html"}).status_code == 409
    unchanged = next(f for f in api.get("/api/tree").json()["feeds"] if f["id"] == tech["id"])
    assert unchanged["url"] == f"{feeds}/tech.xml"

    api.delete(f"/api/feeds/{atom['id']}")
    changed = api.patch(f"/api/feeds/{tech['id']}", json={"url": f"{feeds}/site.html", "title": "Now Atom"}).json()
    assert changed["url"] == f"{feeds}/posts.atom"  # discovered behind the page
    assert changed["title"] == "Now Atom" and changed["folder_id"] == tech["folder_id"]
    assert changed["last_error"] is None
    assert changed["unread"] == 15 + 60  # the old articles stay, the new address's arrive


def test_blank_names_are_rejected_with_a_readable_message(api, subscriptions):
    for response in (
        api.post("/api/folders", json={"name": "   "}),
        api.patch(f"/api/folders/{subscriptions.tech_folder['id']}", json={"name": ""}),
        api.patch(f"/api/feeds/{subscriptions.tech['id']}", json={"title": "  "}),
    ):
        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_rename_and_move_a_feed(api, subscriptions):
    tech = subscriptions.tech["id"]
    renamed = api.patch(f"/api/feeds/{tech}", json={"title": "  My   Tech  "}).json()
    assert renamed["title"] == "My Tech"
    moved = api.patch(f"/api/feeds/{tech}", json={"folder_id": None}).json()
    assert moved["folder_id"] is None
    assert moved["title"] == "My Tech"
    uncategorized = api.get("/api/articles", params={"scope": "uncategorized", "unread_only": "false"}).json()
    assert len(uncategorized["articles"]) == 15
    assert api.patch("/api/feeds/999999", json={"title": "x"}).status_code == 404
    assert api.patch(f"/api/feeds/{tech}", json={"folder_id": 999999}).status_code == 404


def test_folder_rename_conflicts_and_ownership(api, subscriptions):
    blogs = subscriptions.blogs_folder["id"]
    assert api.post("/api/folders", json={"name": "Tech"}).status_code == 409
    assert api.patch(f"/api/folders/{blogs}", json={"name": "Tech"}).status_code == 409
    assert api.patch(f"/api/folders/{blogs}", json={"name": "Writing"}).json()["name"] == "Writing"
    assert api.patch("/api/folders/999999", json={"name": "x"}).status_code == 404


def test_deleting_a_folder_moves_its_feeds_to_uncategorized(api, subscriptions):
    assert api.delete(f"/api/folders/{subscriptions.blogs_folder['id']}").status_code == 200
    tree = api.get("/api/tree").json()
    assert all(f["name"] != "Blogs" for f in tree["folders"])
    assert next(f for f in tree["feeds"] if f["id"] == subscriptions.atom["id"])["folder_id"] is None


def test_deleting_a_folder_can_unfollow_its_feeds(api, subscriptions):
    api.delete(f"/api/folders/{subscriptions.tech_folder['id']}", params={"unfollow": "true"})
    assert [f["id"] for f in api.get("/api/tree").json()["feeds"]] == [subscriptions.atom["id"]]


def test_unfollow_removes_the_feed_and_its_articles(api, subscriptions):
    assert api.delete(f"/api/feeds/{subscriptions.tech['id']}").status_code == 200
    tree = api.get("/api/tree").json()
    assert [f["id"] for f in tree["feeds"]] == [subscriptions.atom["id"]]
    articles = api.get("/api/articles", params={"scope": "all", "unread_only": "false", "limit": 100}).json()
    assert len(articles["articles"]) == 60


def test_manual_refresh_finds_nothing_new(api, subscriptions):
    assert api.post("/api/refresh", json={"scope": "all"}).json() == {"feeds": 2, "new": 0}
    assert api.post("/api/refresh", json={"scope": "feed", "id": subscriptions.tech["id"]}).json()["feeds"] == 1
