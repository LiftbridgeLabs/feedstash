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


def test_a_changed_address_skips_old_entries_so_purged_articles_stay_gone(conn, user_id):
    now = 100 * 365 * DAY
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    ingest.save_entries(conn, feed_id, parsed(entry("old", now - 200 * DAY)), first_fetch=True, retention_days=90, now=now)
    conn.execute("DELETE FROM articles WHERE guid = 'old'")  # what the retention cleanup does

    # The site moved: the new address lists the same old entry. It mustn't come back as unread.
    moved = parsed(entry("old", now - 200 * DAY), entry("new", now))
    assert ingest.save_entries(conn, feed_id, moved, first_fetch=True, keep_old=False, retention_days=90, now=now) == 1
    assert [row[0] for row in conn.execute("SELECT guid FROM articles")] == ["new"]


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


RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>A</title><guid>a</guid></item></channel></rss>'


def _refresh_against(monkeypatch, tmp_path, urls, respond):
    """Follows `urls`, then runs refresh rounds against a mock web where `respond(request)` answers. Returns a
    function that runs one round, the database and the user."""
    import asyncio

    import httpx

    monkeypatch.setattr(ingest, "_resting", {})
    monkeypatch.setattr(ingest, "_site_locks", {})
    monkeypatch.setattr(ingest, "SAME_SITE_GAP_SECONDS", 0)
    monkeypatch.setattr(ingest, "create_client", lambda *_: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    db = Database(tmp_path / "reader.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="s", email="s@example.com", name=None, picture=None)
        for url in urls:
            feeds.create(conn, user_id, url=url, title=url)

    def round_():
        with db.transaction() as conn:
            states = feeds.fetch_states_in_scope(conn, user_id, Scope("all"))
        return asyncio.run(ingest.refresh(db, states, retention_days=90))

    return round_, db, user_id


def test_feeds_on_one_site_are_fetched_one_at_a_time(monkeypatch, tmp_path):
    import asyncio

    import httpx

    in_flight, most = {}, {}

    async def respond(request):
        host = request.url.host
        in_flight[host] = in_flight.get(host, 0) + 1
        most[host] = max(most.get(host, 0), in_flight[host])
        await asyncio.sleep(0.02)
        in_flight[host] -= 1
        return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})

    urls = [f"https://news.example.com/{n}.xml" for n in range(4)] + [f"https://other{n}.example.com/feed" for n in range(3)]
    round_, _, _ = _refresh_against(monkeypatch, tmp_path, urls, respond)
    round_()
    assert most["news.example.com"] == 1
    assert set(most) == {"news.example.com", "other0.example.com", "other1.example.com", "other2.example.com"}


def test_a_site_that_says_too_many_requests_is_left_alone_for_a_while(monkeypatch, tmp_path):
    import httpx

    asked = []

    def respond(request):
        asked.append(str(request.url))
        if request.url.host == "busy.example.com":
            return httpx.Response(429, headers={"retry-after": "120"})
        return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})

    urls = [f"https://busy.example.com/{n}.xml" for n in range(3)] + ["https://calm.example.com/feed"]
    round_, db, user_id = _refresh_against(monkeypatch, tmp_path, urls, respond)
    round_()
    # The first answer stops the round for that site; the others on it aren't asked at all.
    assert sum("busy.example.com" in url for url in asked) == 1
    assert "https://calm.example.com/feed" in asked
    with db.transaction() as conn:
        errors = {feed.url: feed.last_error for feed in feeds.list_for_user(conn, user_id)}
    assert "asked FeedStash to slow down" in errors["https://busy.example.com/0.xml"]
    assert errors["https://busy.example.com/1.xml"] is None

    asked.clear()
    round_()
    assert not any("busy.example.com" in url for url in asked)
    assert "https://calm.example.com/feed" in asked


def test_a_refresh_pressed_during_the_scheduled_round_waits_its_turn_at_each_site(monkeypatch, tmp_path):
    import asyncio

    import httpx

    in_flight = most = 0

    async def respond(request):
        nonlocal in_flight, most
        in_flight += 1
        most = max(most, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})

    urls = ["https://news.example.com/a.xml", "https://news.example.com:443/b.xml"]
    _, db, user_id = _refresh_against(monkeypatch, tmp_path, urls, respond)
    with db.transaction() as conn:
        states = feeds.fetch_states_in_scope(conn, user_id, Scope("all"))

    async def two_at_once():
        await asyncio.gather(*(ingest.refresh(db, states, retention_days=90) for _ in range(2)))

    asyncio.run(two_at_once())
    assert most == 1


def test_a_feed_that_answers_on_https_keeps_that_address(tmp_path):
    db = Database(tmp_path / "reader.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="s", email="s@example.com", name=None, picture=None)
        old = feeds.create(conn, user_id, url="http://a.example.com/feed", title="A")
        both = feeds.create(conn, user_id, url="http://b.example.com/feed", title="B")
        feeds.create(conn, user_id, url="https://b.example.com/feed", title="B again")
    for feed_id, url in ((old, "http://a.example.com/feed"), (both, "http://b.example.com/feed")):
        state = FeedFetchState(id=feed_id, url=url, etag=None, last_modified=None, last_fetched_at=None)
        ingest.store_result(db, state, FetchResult(url="https://" + url[7:], feed=parsed(entry("x", None))), retention_days=90)
    with db.transaction() as conn:
        assert feeds.get(conn, user_id, old).url == "https://a.example.com/feed"
        assert feeds.get(conn, user_id, both).url == "http://b.example.com/feed"  # already followed on https
        # An old OPML file listing the http address counts as already followed.
        assert feeds.is_followed(conn, user_id, "http://a.example.com/feed")
        # An address edited while it was being fetched isn't overwritten.
        edited = feeds.create(conn, user_id, url="http://c.example.com/feed", title="C")
        conn.execute("UPDATE feeds SET url = 'https://elsewhere.example.com/rss' WHERE id = ?", (edited,))
    state = FeedFetchState(id=edited, url="http://c.example.com/feed", etag=None, last_modified=None, last_fetched_at=None)
    ingest.store_result(db, state, FetchResult(url="https://c.example.com/feed", feed=parsed(entry("y", None))), retention_days=90)
    with db.transaction() as conn:
        assert feeds.get(conn, user_id, edited).url == "https://elsewhere.example.com/rss"
