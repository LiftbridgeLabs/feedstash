"""Full text for feed articles: fetched on request, or in the background for feeds that ask for it."""

import time

import pytest


def articles_of(api, feed_id: int) -> dict[str, dict]:
    listed = api.get("/api/articles", params={"scope": "feed", "id": feed_id, "unread_only": "false"}).json()
    return {a["title"]: a for a in listed["articles"]}


def test_an_article_can_fetch_its_full_text_on_request(start_server, feed_server):
    api = start_server(PAGE_CAPTURE="true").login()
    feed = api.post("/api/feeds", json={"url": f"{feed_server}/longreads.xml"}).json()
    assert feed["full_text"] is False
    reef = articles_of(api, feed["id"])["Reef guide"]
    assert api.get(f"/api/articles/{reef['id']}").json()["full_content"] is None

    full = api.post(f"/api/articles/{reef['id']}/full-text").json()
    assert full["status"] == "ready" and full["error"] is None
    assert "Bonaire lets you" in full["content"] and "newsletter" not in full["content"]
    assert f'src="{feed_server}/img/turtle.png"' in full["content"]

    # It's kept with the article, for the web app and for syncing clients.
    assert "Bonaire lets you" in api.get(f"/api/articles/{reef['id']}").json()["full_content"]
    synced = api.post("/api/articles/contents", json={"ids": [reef["id"]]}).json()
    assert "Bonaire lets you" in synced[0]["full_content"]
    assert synced[0]["content"] == "Where to dive first."  # the feed's own content is untouched

    gone = articles_of(api, feed["id"])["Missing page"]
    failed = api.post(f"/api/articles/{gone['id']}/full-text").json()
    assert failed == {"status": "failed", "content": None, "error": "HTTP 404"}
    assert api.post("/api/articles/999999/full-text").status_code == 404


def test_feeds_can_fetch_full_text_for_every_unread_article(start_server, feed_server):
    api = start_server(PAGE_CAPTURE="true").login()
    feed = api.post("/api/feeds", json={"url": f"{feed_server}/longreads.xml"}).json()
    tides = articles_of(api, feed["id"])["Tide tables"]
    api.post("/api/articles/mark", json={"ids": [articles_of(api, feed["id"])["Reef guide"]["id"]], "read": True})

    assert api.patch(f"/api/feeds/{feed['id']}", json={"full_text": True}).json()["full_text"] is True
    assert next(f for f in api.get("/api/tree").json()["feeds"] if f["id"] == feed["id"])["full_text"] is True

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        article = api.get(f"/api/articles/{tides['id']}").json()
        if article["full_content"]:
            break
        time.sleep(0.3)
    else:
        pytest.fail("the full text wasn't fetched in the background")
    assert "Slack water at the reef entrance" in article["full_content"]
    # Articles already read are left alone.
    reef = api.get(f"/api/articles/{articles_of(api, feed['id'])['Reef guide']['id']}").json()
    assert reef["full_content"] is None


def test_servers_that_dont_fetch_pages_say_so(start_server, feed_server):
    api = start_server().login()  # PAGE_CAPTURE is off in tests unless turned on
    feed = api.post("/api/feeds", json={"url": f"{feed_server}/longreads.xml"}).json()
    reef = articles_of(api, feed["id"])["Reef guide"]
    response = api.post(f"/api/articles/{reef['id']}/full-text")
    assert response.status_code == 409 and "PAGE_CAPTURE" in response.json()["detail"]
