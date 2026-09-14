from app.db import Database
from app.db.models import FeedFetchState, Scope
from app.db.repositories import feeds, users
from app.feeds import ingest
from app.feeds.fetcher import FetchResult
from app.feeds.parser import ParsedEntry, ParsedFeed

DAY = 86400


def entry(guid: str, published_at: int | None) -> ParsedEntry:
    return ParsedEntry(guid=guid, title=guid, url=None, author=None, summary="", content="", image=None,
                       published_at=published_at)


def parsed(*entries: ParsedEntry) -> ParsedFeed:
    return ParsedFeed(title="Feed", site_url="https://site.example.com/", entries=list(entries))


def test_first_fetch_keeps_old_entries_but_later_fetches_skip_them(conn, user_id):
    now = 100 * 365 * DAY
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")

    first = parsed(entry("old", now - 200 * DAY), entry("recent", now - 60), entry("undated", None))
    assert ingest.save_entries(conn, feed_id, first, first_fetch=True, retention_days=90, now=now) == 3
    undated = conn.execute("SELECT published_at FROM articles WHERE guid = 'undated'").fetchone()[0]
    assert undated == now

    later = parsed(entry("old-2", now - 200 * DAY), entry("recent-2", now))
    assert ingest.save_entries(conn, feed_id, later, first_fetch=False, retention_days=90, now=now) == 1


def test_store_result_records_feed_status(tmp_path):
    db = Database(tmp_path / "reader.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="s", email="s@example.com", name=None, picture=None)
        feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    state = FeedFetchState(id=feed_id, url="https://a.example.com/feed", etag=None, last_modified=None, last_fetched_at=None)
    result = FetchResult(url=state.url, feed=parsed(entry("a", None), entry("b", None)), etag='"e1"', last_modified="Mon")

    assert ingest.store_result(db, state, result, retention_days=90) == 2
    with db.transaction() as conn:
        (stored,) = feeds.fetch_states_in_scope(conn, user_id, Scope("all"))
        assert stored.etag == '"e1"' and stored.last_fetched_at is not None
        assert feeds.get(conn, user_id, feed_id).site_url == "https://site.example.com/"

    ingest.record_error(db, feed_id, "HTTP 500")
    with db.transaction() as conn:
        assert feeds.get(conn, user_id, feed_id).last_error == "HTTP 500"

    not_modified = FetchResult(url=state.url, feed=None)
    assert ingest.store_result(db, state, not_modified, retention_days=90) == 0
    with db.transaction() as conn:
        assert feeds.get(conn, user_id, feed_id).last_error is None
        feeds.delete(conn, user_id, feed_id)
    # A feed unfollowed while it was being fetched is simply skipped.
    assert ingest.store_result(db, state, result, retention_days=90) == 0
