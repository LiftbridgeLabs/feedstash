"""Stores what the fetcher downloaded, and refreshes batches of feeds."""

import asyncio
import logging
import sqlite3
from collections.abc import Sequence

from app.clock import now as current_time
from app.db import Database
from app.db.models import FeedFetchState, NewArticle
from app.db.repositories import articles as articles_repo
from app.db.repositories import feeds as feeds_repo
from app.feeds.fetcher import Fetcher, FetchError, FetchResult, create_client
from app.feeds.parser import ParsedFeed
from app.feeds.to_stash import stash_article
from app.text import html_to_text

log = logging.getLogger("reader.ingest")

REFRESH_CONCURRENCY = 8
DAY_SECONDS = 86400


def save_entries(
    conn: sqlite3.Connection, feed_id: int, feed: ParsedFeed, *, first_fetch: bool, retention_days: int, now: int
) -> int:
    """Stores a feed's new entries. Returns how many were new.

    Entries older than the retention window are only accepted on a feed's first fetch; afterwards
    they would just bring back articles the cleanup already removed. Undated entries count as `now`.
    On a feed set to auto-save, new articles also go to the stash, except on a first fetch (a whole
    backlog arriving at once).
    """
    cutoff = now - retention_days * DAY_SECONDS
    fresh = []
    for entry in feed.entries:
        published_at = entry.published_at or now
        if published_at < cutoff and not first_fetch:
            continue
        fresh.append(NewArticle(
            guid=entry.guid, title=entry.title, url=entry.url, author=entry.author, summary=entry.summary,
            content=entry.content, image=entry.image, published_at=published_at,
            search_text=html_to_text(entry.content or entry.summary),
        ))
    added_ids: list[int] = []
    added = articles_repo.insert_new(conn, feed_id, fresh, fetched_at=now, added_ids=added_ids)
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
    """Fetches feeds concurrently and stores the results. Failures are recorded per feed, never raised."""
    if not feeds:
        return 0
    semaphore = asyncio.Semaphore(REFRESH_CONCURRENCY)
    async with create_client(REFRESH_CONCURRENCY * 2) as client:
        fetcher = Fetcher(client)

        async def refresh_one(feed: FeedFetchState) -> int:
            async with semaphore:
                try:
                    result = await fetcher.fetch(feed.url, etag=feed.etag, last_modified=feed.last_modified)
                    return await asyncio.to_thread(store_result, db, feed, result, retention_days=retention_days)
                except FetchError as exc:
                    message = str(exc) or "Fetch failed"
                except Exception as exc:
                    log.exception("Unexpected error refreshing %s", feed.url)
                    message = f"Unexpected error: {exc.__class__.__name__}"
                await asyncio.to_thread(record_error, db, feed.id, message)
                return 0

        results = await asyncio.gather(*(refresh_one(feed) for feed in feeds))
    return sum(results)
