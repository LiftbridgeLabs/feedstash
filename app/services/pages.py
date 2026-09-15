"""Saves the web pages behind stash items in the background: link previews, readable copies and search text.

Items queue their page when they're saved or their address changes (see the items repository); this worker
fetches what's due. Run it in one process only, like the feed refresher.
"""

import asyncio
import contextlib
import logging
import sqlite3

from app.clock import now
from app.db import Database
from app.db.models import PageJob
from app.db.repositories import items as items_repo
from app.db.repositories import pages as pages_repo
from app.db.repositories import search
from app.pages.fetch import NotAWebPage, Page, PageBlocked, PageError, create_client, fetch_page

log = logging.getLogger("feedstash.pages")

BATCH_SIZE = 4
IDLE_SECONDS = 2


def store_page(conn: sqlite3.Connection, job: PageJob, page: Page, *, now: int) -> bool:
    """Saves a page (fetched here, or sent by a client that had it open), gives an untitled item the page's title,
    and reindexes the item. False when the item was deleted or its address changed meanwhile."""
    saved = pages_repo.save_ready(
        conn, job, now=now, title=page.title, description=page.description, image_url=page.image_url,
        site_name=page.site_name, text=page.text, html=page.html,
    )
    if saved:
        items_repo.set_title_if_missing(conn, job.item_id, page.title)
        search.index_item(conn, job.item_id)
    return saved


class PageWorker:
    def __init__(self, db: Database):
        self._db = db
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="page-capture")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> int:
        """Fetches the pages that are due. Returns how many were handled."""
        jobs = await asyncio.to_thread(self._claim)
        if jobs:
            async with create_client() as client:
                await asyncio.gather(*(self._handle(client, job) for job in jobs))
        return len(jobs)

    def _claim(self) -> list[PageJob]:
        with self._db.transaction() as conn:
            return pages_repo.claim(conn, now=now(), limit=BATCH_SIZE)

    async def _handle(self, client, job: PageJob) -> None:
        try:
            page = await fetch_page(client, job.url)
        except NotAWebPage as exc:
            await asyncio.to_thread(self._skipped, job, str(exc))
        except PageBlocked as exc:
            await asyncio.to_thread(self._failed, job, str(exc), True)
        except PageError as exc:
            await asyncio.to_thread(self._failed, job, str(exc))
        except Exception as exc:
            log.exception("Unexpected error saving %s", job.url)
            await asyncio.to_thread(self._failed, job, f"Unexpected error ({exc.__class__.__name__})")
        else:
            await asyncio.to_thread(self._ready, job, page)

    def _ready(self, job: PageJob, page: Page) -> None:
        with self._db.transaction() as conn:
            store_page(conn, job, page, now=now())

    def _skipped(self, job: PageJob, reason: str) -> None:
        with self._db.transaction() as conn:
            pages_repo.save_skipped(conn, job, now=now(), reason=reason)

    def _failed(self, job: PageJob, error: str, final: bool = False) -> None:
        with self._db.transaction() as conn:
            pages_repo.save_failure(conn, job, now=now(), error=error, final=final)

    async def _run(self) -> None:
        await asyncio.sleep(1)
        while True:
            try:
                handled = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Saving pages failed")
                handled = 0
            if not handled:
                await asyncio.sleep(IDLE_SECONDS)
