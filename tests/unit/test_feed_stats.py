"""Feed info: what a feed posted lately and what became of it."""

import pytest

from app.db.repositories import feeds, users
from app.errors import NotFound

DAY = 86_400
NOW = 2_000_000_000


def _article(conn, feed_id, guid, *, days_ago, read=False, starred=False):
    conn.execute(
        """INSERT INTO articles (feed_id, guid, title, published_at, fetched_at, read_at, starred_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (feed_id, guid, guid, NOW - days_ago * DAY, NOW, NOW if read else None, NOW if starred else None),
    )


def test_counts_cover_the_last_four_weeks(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    for n in range(8):
        _article(conn, feed_id, f"new-{n}", days_ago=n * 3, read=n < 6, starred=n == 0)
    _article(conn, feed_id, "old", days_ago=40, read=True)
    conn.execute("INSERT INTO items (user_id, type, title, created_at, updated_at, feed_id) VALUES (?, 'link', 'x', ?, ?, ?)",
                 (user_id, NOW - DAY, NOW - DAY, feed_id))
    stats = feeds.stats(conn, user_id, feed_id, now=NOW, read_retention_days=30)
    assert (stats.window_days, stats.posted, stats.read, stats.starred, stats.saved) == (28, 8, 6, 1, 1)


def test_a_short_read_retention_shortens_the_window(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    _article(conn, feed_id, "today", days_ago=0)
    _article(conn, feed_id, "last-week", days_ago=8)
    assert feeds.stats(conn, user_id, feed_id, now=NOW, read_retention_days=7).posted == 1
    assert feeds.stats(conn, user_id, feed_id, now=NOW, read_retention_days=7).window_days == 7
    assert feeds.stats(conn, user_id, feed_id, now=NOW, read_retention_days=0).window_days == 28


def test_only_your_own_feeds(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    other = users.upsert(conn, sub="sub-bob", email="bob@example.com", name=None, picture=None)
    with pytest.raises(NotFound):
        feeds.stats(conn, other, feed_id, now=NOW, read_retention_days=30)
