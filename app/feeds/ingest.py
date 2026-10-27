"""Stores what the fetcher downloaded, and refreshes batches of feeds."""

import asyncio
import logging
import sqlite3
import time
from collections import defaultdict
from collections.abc import Sequence
from urllib.parse import urlparse

from app.clock import now as current_time
from app.db import Database
from app.db.models import FeedFetchState, NewArticle
from app.db.repositories import articles as articles_repo
from app.db.repositories import feeds as feeds_repo
from app.feeds.fetcher import Fetcher, FetchError, FetchResult, RateLimited, create_client, secure_url
from app.feeds.parser import ParsedFeed
from app.feeds.to_stash import stash_article
from app.text import html_to_text

log = logging.getLogger("reader.ingest")

REFRESH_CONCURRENCY = 8
DAY_SECONDS = 86400
# Feeds on one site are fetched one after another, this far apart: several at once from the same address is what
# small sites' rate limits turn away.
SAME_SITE_GAP_SECONDS = 2.0
# After a site answers "too many requests", its feeds are left alone as long as it asked (a minute to six hours),
# or an hour if it didn't say. Kept in memory: a restart simply tries again.
REST_SECONDS = 3600
MAX_REST_SECONDS = 6 * 3600
_resting: dict[str, float] = {}  # site -> time.monotonic() when it may be asked again
# One refresh at a time talks to a site, so a press of Refresh during the scheduled round waits its turn there.
# Every refresh (scheduler, Refresh, OPML import) runs on the server's one event loop, so asyncio locks suffice.
_site_locks: dict[str, asyncio.Lock] = {}


def save_entries(
    conn: sqlite3.Connection, feed_id: int, feed: ParsedFeed, *, first_fetch: bool, retention_days: int, now: int,
    keep_old: bool | None = None,
) -> int:
    """Stores a feed's new entries. Returns how many were new.

    Entries older than the retention window are only accepted on a feed's first fetch (`keep_old` defaults to
    `first_fetch`); afterwards they would just bring back articles the cleanup already removed. Undated entries
    count as `now`. On a feed set to auto-save, new articles also go to the stash, except on a first fetch (a
    whole backlog arriving at once).
    """
    keep_old = first_fetch if keep_old is None else keep_old
    cutoff = now - retention_days * DAY_SECONDS
    fresh = []
    for entry in feed.entries:
        published_at = entry.published_at or now
        if published_at < cutoff and not keep_old:
            continue
        fresh.append(NewArticle(
            guid=entry.guid, title=entry.title, url=entry.url, author=entry.author, summary=entry.summary,
            content=entry.content, image=entry.image, published_at=published_at,
            search_text=html_to_text(entry.content or entry.summary),
        ))
    added_ids: list[int] = []
    added = articles_repo.insert_new(conn, feed_id, fresh, fetched_at=now, added_ids=added_ids)
    if added:
        feeds_repo.mark_new_articles(conn, feed_id, at=now)
    if added_ids and not first_fetch:
        _auto_stash(conn, feed_id, added_ids, now=now)
    return added


def _auto_stash(conn: sqlite3.Connection, feed_id: int, article_ids: list[int], *, now: int) -> None:
    """New articles of a feed set to auto-save go to its owner's stash, and are marked read in the feed."""
    user_id = feeds_repo.auto_stash_owner(conn, feed_id)
    if user_id is None:
        return
    for article_id in article_ids:
        stash_article(conn, user_id, articles_repo.get(conn, user_id, article_id), now=now)
    articles_repo.set_read(conn, user_id, article_ids, read=True, now=now)


def store_result(db: Database, feed: FeedFetchState, result: FetchResult, *, retention_days: int) -> int:
    now = current_time()
    with db.transaction() as conn:
        if not feeds_repo.exists(conn, feed.id):
            return 0  # unfollowed while we were fetching
        # The same feed followed again under the address this one now ends up at, or its https one (possible before
        # 0.9.0): storing here would bring every story twice, so this older copy stops.
        twin = feeds_repo.followed_as_another(
            conn, feed.id, [url for url in {result.url, secure_url(feed.url)} if url and url != feed.url],
        )
        if twin is not None:
            feeds_repo.record_checked(conn, feed.id, fetched_at=now, error=(
                f"You also follow this feed as {twin}, so this copy no longer updates. Unfollow this one."
            ))
            return 0
        if result.url == secure_url(feed.url):  # it answered on https after refusing http (or redirected there)
            feeds_repo.upgrade_to_https(conn, feed.id, feed.url, result.url)
        if result.not_modified:
            feeds_repo.record_checked(conn, feed.id, fetched_at=now, error=None)
            return 0
        added = save_entries(
            conn, feed.id, result.feed,
            first_fetch=feed.last_fetched_at is None, retention_days=retention_days, now=now,
        )
        feeds_repo.record_success(
            conn, feed.id, fetched_at=now, etag=result.etag, last_modified=result.last_modified,
            site_url=result.feed.site_url,
        )
        return added


def record_error(db: Database, feed_id: int, message: str) -> None:
    with db.transaction() as conn:
        feeds_repo.record_checked(conn, feed_id, fetched_at=current_time(), error=message[:500])


async def refresh(db: Database, feeds: Sequence[FeedFetchState], *, retention_days: int) -> int:
    """Fetches feeds and stores the results: different sites concurrently, one site's feeds one at a time. Feeds of
    a site that recently said "too many requests" wait for the next round after its rest. Failures are recorded
    per feed, never raised."""
    if not feeds:
        return 0
    by_site: dict[str, list[FeedFetchState]] = defaultdict(list)
    for feed in feeds:
        by_site[_site(feed.url)].append(feed)
    semaphore = asyncio.Semaphore(REFRESH_CONCURRENCY)
    async with create_client(REFRESH_CONCURRENCY * 2) as client:
        fetcher = Fetcher(client)

        async def refresh_one(site: str, feed: FeedFetchState) -> int:
            async with semaphore:
                try:
                    result = await fetcher.fetch(feed.url, etag=feed.etag, last_modified=feed.last_modified)
                    return await asyncio.to_thread(store_result, db, feed, result, retention_days=retention_days)
                except RateLimited as exc:
                    rest = REST_SECONDS if exc.retry_after is None else min(max(exc.retry_after, 60), MAX_REST_SECONDS)
                    _resting[site] = time.monotonic() + rest
                    log.info("%s is rate limiting feed fetches; leaving it for %d minutes", site, rest // 60)
                    message = str(exc)
                except FetchError as exc:
                    message = str(exc) or "Fetch failed"
                except Exception as exc:
                    log.exception("Unexpected error refreshing %s", feed.url)
                    message = f"Unexpected error: {exc.__class__.__name__}"
                await asyncio.to_thread(record_error, db, feed.id, message)
                return 0

        async def refresh_site(site: str, site_feeds: list[FeedFetchState]) -> int:
            added = 0
            async with _site_locks.setdefault(site, asyncio.Lock()):
                for index, feed in enumerate(site_feeds):
                    if _resting.get(site, 0) > time.monotonic():
                        break
                    if index:
                        await asyncio.sleep(SAME_SITE_GAP_SECONDS)
                    added += await refresh_one(site, feed)
            return added

        results = await asyncio.gather(*(refresh_site(site, group) for site, group in by_site.items()))
    return sum(results)


def _site(url: str) -> str:
    """The host, with its port only when it isn't the default, so one site written two ways is still one site."""
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    return host if port in (None, 80, 443) else f"{host}:{port}"
