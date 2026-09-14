"""Following feeds and importing OPML."""

import asyncio
from dataclasses import dataclass

from app import opml
from app.clock import now as current_time
from app.db import Database
from app.db.models import Feed, FeedFetchState
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import folders as folders_repo
from app.errors import Conflict, InvalidInput
from app.feeds import ingest
from app.feeds.fetcher import Fetcher, FetchError, FetchResult, create_client
from app.settings import Settings
from app.text import collapse_whitespace


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int
    skipped: int
    folders_created: int
    pending: list[FeedFetchState]  # imported feeds that still need their first fetch


async def follow(
    db: Database,
    settings: Settings,
    user_id: int,
    *,
    url: str,
    folder_id: int | None = None,
    folder_name: str | None = None,
    title: str | None = None,
) -> Feed:
    """Finds the feed behind `url`, subscribes to it (optionally in a new folder) and stores its articles."""
    try:
        async with create_client() as client:
            result = await Fetcher(client).discover(url)
    except FetchError as exc:
        raise InvalidInput(str(exc)) from exc
    return await asyncio.to_thread(
        _save_followed, db, settings, user_id, result, folder_id=folder_id, folder_name=folder_name, title=title
    )


def _save_followed(
    db: Database, settings: Settings, user_id: int, result: FetchResult, *,
    folder_id: int | None, folder_name: str | None, title: str | None,
) -> Feed:
    now = current_time()
    with db.transaction() as conn:
        if feeds_repo.is_followed(conn, user_id, result.url):
            raise Conflict("You already follow this feed")
        if collapse_whitespace(folder_name):
            folder_id = folders_repo.get_or_create(conn, user_id, folder_name).id
        feed_id = feeds_repo.create(
            conn, user_id,
            url=result.url,
            title=title if collapse_whitespace(title) else result.feed.title,
            folder_id=folder_id,
            site_url=result.feed.site_url,
            etag=result.etag,
            last_modified=result.last_modified,
            fetched_at=now,
        )
        ingest.save_entries(conn, feed_id, result.feed, first_fetch=True, retention_days=settings.retention_days, now=now)
        return feeds_repo.get(conn, user_id, feed_id)


def import_opml(db: Database, user_id: int, data: bytes) -> ImportResult:
    """Adds the OPML file's feeds (skipping ones already followed). Articles are fetched later."""
    try:
        outlines = opml.parse_opml(data)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc

    added = skipped = 0
    with db.transaction() as conn:
        folders_before = folders_repo.names(conn, user_id)
        for folder_name, url, title in outlines:
            if not url.lower().startswith(("http://", "https://")) or feeds_repo.is_followed(conn, user_id, url):
                skipped += 1
                continue
            folder_id = folders_repo.get_or_create(conn, user_id, folder_name).id if folder_name else None
            feeds_repo.create(conn, user_id, url=url, title=collapse_whitespace(title) or url, folder_id=folder_id)
            added += 1
        folders_created = len(folders_repo.names(conn, user_id) - folders_before)
        pending = feeds_repo.never_fetched(conn, user_id)
    return ImportResult(added=added, skipped=skipped, folders_created=folders_created, pending=pending)
