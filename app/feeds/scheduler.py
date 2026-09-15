"""Background refresh: fetches due feeds every minute and purges old articles every hour.

Run it in exactly one process (see SCHEDULER_ENABLED); several would fetch every feed several times.
"""

import asyncio
import contextlib
import logging
import time

from app.clock import now
from app.db import Database
from app.db.repositories import articles as articles_repo
from app.db.repositories import feeds as feeds_repo
from app.feeds import ingest
from app.settings import Settings

log = logging.getLogger("reader.scheduler")

TICK_SECONDS = 60
PURGE_EVERY_SECONDS = 3600
DAY_SECONDS = 86400


class RefreshScheduler:
    def __init__(self, db: Database, settings: Settings):
        self._db = db
        self._settings = settings
        self._task: asyncio.Task | None = None
        self._last_purge = float("-inf")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="feed-refresh")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> int:
        """One tick: refresh feeds that are due, and purge if an hour has passed. Returns new article count."""
        fetched_before = now() - self._settings.refresh_interval_minutes * 60 + 30
        due = await asyncio.to_thread(self._due_feeds, fetched_before)
        added = 0
        if due:
            started = time.monotonic()
            added = await ingest.refresh(self._db, due, retention_days=self._settings.retention_days)
            log.info("Refreshed %d feeds in %.1fs, %d new articles", len(due), time.monotonic() - started, added)
        if time.monotonic() - self._last_purge >= PURGE_EVERY_SECONDS:
            old, read = await asyncio.to_thread(self._purge)
            self._last_purge = time.monotonic()
            if old or read:
                log.info(
                    "Purged %d articles older than %d days and %d read articles", old, self._settings.retention_days, read
                )
        return added

    def _due_feeds(self, fetched_before: int):
        with self._db.transaction() as conn:
            return feeds_repo.due_for_refresh(conn, fetched_before=fetched_before)

    def _purge(self) -> tuple[int, int]:
        """Deletes articles past the server's retention, then read articles past each owner's setting."""
        current = now()
        cutoff = current - self._settings.retention_days * DAY_SECONDS
        with self._db.transaction() as conn:
            old = articles_repo.purge(conn, published_before=cutoff, keep_per_feed=self._settings.keep_per_feed)
            read = articles_repo.purge_read(conn, now=current)
            articles_repo.forget_purged(conn, published_before=cutoff)
        return old, read

    async def _run(self) -> None:
        await asyncio.sleep(3)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Feed refresh failed")
            await asyncio.sleep(TICK_SECONDS)
