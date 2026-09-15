"""The web pages behind stash items: a queue of pages to fetch, then each page's preview and readable copy."""

import sqlite3
from collections.abc import Sequence

from app.db.models import PageCopy, PageJob, PagePreview
from app.errors import NotFound

MAX_ATTEMPTS = 3
RETRY_DELAYS = (60, 15 * 60)  # after the first and the second failed attempt
STALE_WORK_SECONDS = 10 * 60  # a fetch still "working" after this long was interrupted (e.g. by a restart)


def is_web_url(url: str | None) -> bool:
    return bool(url) and url.lower().startswith(("http://", "https://"))


def queue(conn: sqlite3.Connection, item_id: int, url: str | None, *, now: int) -> None:
    """Asks for an item's page to be fetched when its address is new or changed; forgets it when there's none."""
    if not is_web_url(url):
        conn.execute("DELETE FROM item_pages WHERE item_id = ?", (item_id,))
        return
    row = conn.execute("SELECT url FROM item_pages WHERE item_id = ?", (item_id,)).fetchone()
    if row and row["url"] == url:
        return
    conn.execute(
        """INSERT INTO item_pages (item_id, url, status, attempts, not_before) VALUES (?, ?, 'pending', 0, ?)
           ON CONFLICT(item_id) DO UPDATE SET url = excluded.url, status = 'pending', attempts = 0,
               not_before = excluded.not_before, error = NULL, fetched_at = NULL, title = NULL, description = NULL,
               image_url = NULL, site_name = NULL, text = NULL, html = NULL""",
        (item_id, url, now),
    )


def queue_missing(conn: sqlite3.Connection, *, now: int) -> int:
    """Queues the pages of items saved before pages were captured. Returns how many."""
    return conn.execute(
        """INSERT INTO item_pages (item_id, url, not_before)
           SELECT id, url, ? FROM items
           WHERE (url LIKE 'http://%' OR url LIKE 'https://%') AND id NOT IN (SELECT item_id FROM item_pages)""",
        (now,),
    ).rowcount


def requeue(conn: sqlite3.Connection, user_id: int, item_id: int, *, now: int) -> None:
    """Fetches an item's page again."""
    updated = conn.execute(
        """UPDATE item_pages SET status = 'pending', attempts = 0, not_before = ?, error = NULL
           WHERE item_id = ? AND item_id IN (SELECT id FROM items WHERE user_id = ?)""",
        (now, item_id, user_id),
    ).rowcount
    if not updated:
        raise NotFound("This item has no web page to save")


def claim(conn: sqlite3.Connection, *, now: int, limit: int) -> list[PageJob]:
    """Marks up to `limit` due pages as being fetched and returns them."""
    rows = conn.execute(
        """UPDATE item_pages SET status = 'working', attempts = attempts + 1, not_before = ?
           WHERE item_id IN (
               SELECT item_id FROM item_pages
               WHERE status IN ('pending', 'working') AND not_before <= ?
               ORDER BY not_before, item_id LIMIT ?
           )
           RETURNING item_id, url, attempts""",
        (now + STALE_WORK_SECONDS, now, limit),
    ).fetchall()
    return [PageJob(item_id=row["item_id"], url=row["url"], attempts=row["attempts"]) for row in rows]


def save_ready(
    conn: sqlite3.Connection, job: PageJob, *, now: int, title: str | None, description: str | None,
    image_url: str | None, site_name: str | None, text: str | None, html: str | None,
) -> bool:
    """Stores a fetched page. False when the item was deleted or its address changed while it was being fetched."""
    return conn.execute(
        """UPDATE item_pages SET status = 'ready', error = NULL, fetched_at = ?, title = ?, description = ?,
               image_url = ?, site_name = ?, text = ?, html = ?
           WHERE item_id = ? AND url = ?""",
        (now, title, description, image_url, site_name, text, html, job.item_id, job.url),
    ).rowcount == 1


def save_skipped(conn: sqlite3.Connection, job: PageJob, *, now: int, reason: str) -> None:
    """The address isn't a web page (a PDF, an image...): there's nothing to save, and no point retrying."""
    conn.execute(
        "UPDATE item_pages SET status = 'skipped', error = ?, fetched_at = ? WHERE item_id = ? AND url = ?",
        (reason, now, job.item_id, job.url),
    )


def save_failure(conn: sqlite3.Connection, job: PageJob, *, now: int, error: str, final: bool = False) -> None:
    """Tries again later, up to MAX_ATTEMPTS in all, then gives up; `final` gives up right away."""
    if final or job.attempts >= MAX_ATTEMPTS:
        conn.execute(
            "UPDATE item_pages SET status = 'failed', error = ?, fetched_at = ? WHERE item_id = ? AND url = ?",
            (error, now, job.item_id, job.url),
        )
        return
    delay = RETRY_DELAYS[min(job.attempts, len(RETRY_DELAYS)) - 1]
    conn.execute(
        "UPDATE item_pages SET status = 'pending', error = ?, not_before = ? WHERE item_id = ? AND url = ?",
        (error, now + delay, job.item_id, job.url),
    )


def previews(conn: sqlite3.Connection, item_ids: Sequence[int]) -> dict[int, PagePreview]:
    if not item_ids:
        return {}
    rows = conn.execute(
        f"""SELECT item_id, status, title, description, image_url, site_name, html IS NOT NULL AS has_copy,
                   fetched_at, error
            FROM item_pages WHERE item_id IN ({','.join('?' * len(item_ids))})""",
        list(item_ids),
    )
    return {
        row["item_id"]: PagePreview(
            status=row["status"], title=row["title"], description=row["description"], image_url=row["image_url"],
            site_name=row["site_name"], has_copy=bool(row["has_copy"]), fetched_at=row["fetched_at"],
            error=row["error"],
        )
        for row in rows
    }


def get_copy(conn: sqlite3.Connection, user_id: int, item_id: int) -> PageCopy:
    row = conn.execute(
        """SELECT p.url, p.status, p.title, p.html, p.fetched_at, p.error
           FROM item_pages p JOIN items i ON i.id = p.item_id WHERE p.item_id = ? AND i.user_id = ?""",
        (item_id, user_id),
    ).fetchone()
    if row is None:
        raise NotFound("This item has no saved page")
    return PageCopy(
        url=row["url"], status=row["status"], title=row["title"], html=row["html"], fetched_at=row["fetched_at"],
        error=row["error"],
    )
