"""The page worker asks for full-text work every couple of seconds, so the claim has to stay cheap and exact."""

from app.db.models import NewArticle
from app.db.repositories import articles, feeds

NOW = 1_000_000


def add_articles(conn, feed_id: int, count: int) -> list[int]:
    items = [NewArticle(guid=f"{feed_id}-{i}", title=f"T{i}", url=f"https://example.com/{feed_id}/{i}", author=None,
                        summary="", content="", image=None, published_at=NOW - i) for i in range(count)]
    articles.insert_new(conn, feed_id, items, fetched_at=NOW)
    return [row[0] for row in conn.execute("SELECT id FROM articles WHERE feed_id = ? ORDER BY id", (feed_id,))]


def test_nothing_is_queried_when_no_feed_asks_for_full_text(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    add_articles(conn, feed_id, 3)
    statements = []
    conn.set_trace_callback(statements.append)
    assert articles.claim_full_text(conn, now=NOW, limit=4) == []
    conn.set_trace_callback(None)
    assert not any("FROM articles" in sql for sql in statements)


def test_claims_untried_unread_articles_once_and_uses_the_partial_index(conn, user_id):
    wanted = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    other = feeds.create(conn, user_id, url="https://b.example.com/feed", title="B")
    ids = add_articles(conn, wanted, 3)
    add_articles(conn, other, 2)
    feeds.set_full_text(conn, user_id, wanted, True)
    articles.set_read(conn, user_id, [ids[0]], read=True, now=NOW)

    claimed = articles.claim_full_text(conn, now=NOW, limit=10)
    assert sorted(job.article_id for job in claimed) == ids[1:]
    assert articles.claim_full_text(conn, now=NOW, limit=10) == []  # being worked on

    plan = " ".join(row[3] for row in conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM articles INDEXED BY idx_articles_full_text_due "
        "WHERE feed_id IN (?) AND full_status IS NULL AND read_at IS NULL", (wanted,)))
    assert "USING INDEX idx_articles_full_text_due" in plan


def test_fetches_cut_off_by_a_restart_are_tried_again(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    ids = add_articles(conn, feed_id, 2)
    feeds.set_full_text(conn, user_id, feed_id, True)
    assert len(articles.claim_full_text(conn, now=NOW, limit=10)) == 2
    assert articles.reset_interrupted_full_text(conn) == 2
    assert sorted(job.article_id for job in articles.claim_full_text(conn, now=NOW, limit=10)) == ids
