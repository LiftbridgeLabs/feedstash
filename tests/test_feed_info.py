"""Feed info over the API."""


def test_feed_stats_say_how_much_a_feed_posts_and_what_you_read(api, subscriptions):
    feed_id = subscriptions.tech["id"]
    stats = api.get(f"/api/feeds/{feed_id}/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert set(body) == {"window_days", "posted", "posts_per_week", "read", "starred", "saved"}
    assert body["window_days"] == 28 and body["read"] == 0
    assert body["posts_per_week"] == round(body["posted"] * 7 / 28, 1)
    assert api.get("/api/feeds/999999/stats").status_code == 404
