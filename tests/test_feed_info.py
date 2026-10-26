"""Feed info and Discover over the API."""

import sqlite3


def test_feed_stats_say_how_much_a_feed_posts_and_what_you_read(api, subscriptions):
    feed_id = subscriptions.tech["id"]
    stats = api.get(f"/api/feeds/{feed_id}/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert set(body) == {"window_days", "posted", "posts_per_week", "read", "starred", "saved"}
    assert body["window_days"] == 28 and body["read"] == 0
    assert body["posts_per_week"] == round(body["posted"] * 7 / 28, 1)
    assert api.get("/api/feeds/999999/stats").status_code == 404


def test_discover_lists_packs_and_marks_what_you_follow(api, server):
    packs = api.get("/api/discover").json()["packs"]
    tech = next(pack for pack in packs if pack["id"] == "tech")
    assert all(not feed["followed"] for feed in tech["feeds"])
    first = tech["feeds"][0]
    # Following goes through the normal endpoint; here the feed is added straight to the database to stay offline.
    with sqlite3.connect(server.db_path) as db:
        user = db.execute("SELECT id FROM users").fetchone()[0]
        db.execute("INSERT INTO feeds (user_id, url, title, created_at) VALUES (?, ?, ?, 0)", (user, first["url"].replace("https://", "http://"), "x"))
    tech = next(pack for pack in api.get("/api/discover").json()["packs"] if pack["id"] == "tech")
    assert tech["feeds"][0]["followed"] is True and not tech["feeds"][1]["followed"]
