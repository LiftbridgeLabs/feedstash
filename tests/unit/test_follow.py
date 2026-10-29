"""Following a feed when the site says "too many requests"."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.db import Database
from app.db.models import Scope
from app.db.repositories import feeds, users
from app.errors import InvalidInput
from app.feeds import ingest
from app.services import subscriptions

RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>A</title><guid>a</guid></item></channel></rss>'
SETTINGS = SimpleNamespace(retention_days=90)


@pytest.fixture
def web(monkeypatch, tmp_path):
    """A database, a user and a mock web where reddit.com says "too many requests" and other sites serve a feed.
    `asked` lists every address requested."""
    asked = []

    def respond(request):
        asked.append(str(request.url))
        if request.url.path == "/r/nosuchplace/.rss":
            return httpx.Response(404)
        if request.url.host == "www.reddit.com" or request.url.host == "busy.example.com":
            return httpx.Response(429)
        return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})

    client = lambda *_: httpx.AsyncClient(transport=httpx.MockTransport(respond))  # noqa: E731
    monkeypatch.setattr(subscriptions, "create_client", client)
    monkeypatch.setattr(ingest, "create_client", client)
    monkeypatch.setattr(ingest, "_resting", {})
    monkeypatch.setattr(ingest, "_site_locks", {})
    db = Database(tmp_path / "reader.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="s", email="s@example.com", name=None, picture=None)
    return SimpleNamespace(db=db, user_id=user_id, asked=asked)


def _follow(web, url, **kwargs):
    return asyncio.run(subscriptions.follow(web.db, SETTINGS, web.user_id, url=url, **kwargs))


def test_a_subreddit_is_followed_even_when_reddit_says_wait(web):
    feed = _follow(web, "r/selfhosted", folder_name="Reddit")
    assert (feed.url, feed.title, feed.last_fetched_at) == ("https://www.reddit.com/r/selfhosted/.rss", "r/selfhosted", None)
    assert "Reddit asked FeedStash to wait" in feed.last_error
    assert feed.folder_id is not None

    # Reddit is left alone for its rest: the next refresh doesn't ask it again, and the feed is still waiting.
    web.asked.clear()
    with web.db.transaction() as conn:
        states = feeds.fetch_states_in_scope(conn, web.user_id, Scope("all"))
    asyncio.run(ingest.refresh(web.db, states, retention_days=90))
    assert web.asked == []
    with web.db.transaction() as conn:
        assert feeds.get(conn, web.user_id, feed.id).last_fetched_at is None


def test_a_name_given_for_the_subreddit_is_kept(web):
    assert _follow(web, "r/selfhosted", title="Self-hosting").title == "Self-hosting"


def test_a_subreddit_that_isnt_there_says_so(web):
    with pytest.raises(InvalidInput, match="Reddit has no subreddit called r/nosuchplace"):
        _follow(web, "r/nosuchplace")


def test_another_site_saying_wait_is_still_an_error(web):
    with pytest.raises(InvalidInput, match="slow down"):
        _follow(web, "https://busy.example.com/feed")
    with web.db.transaction() as conn:
        assert feeds.list_for_user(conn, web.user_id) == []


def test_a_shorter_wait_never_cuts_a_longer_rest_short(monkeypatch):
    monkeypatch.setattr(ingest, "_resting", {})
    ingest.rest_site("https://www.reddit.com/r/a/.rss", 3000)
    longer = ingest._resting["www.reddit.com"]
    ingest.rest_site("https://www.reddit.com/r/b/.rss", 60)
    assert ingest._resting["www.reddit.com"] == longer
