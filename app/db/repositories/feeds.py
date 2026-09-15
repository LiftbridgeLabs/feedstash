import sqlite3
from collections.abc import Sequence

from app.clock import now
from app.db.models import Feed, FeedFetchState, Scope
from app.db.repositories import folders as folders_repo
from app.db.repositories._common import clean_name, next_position, ordered_ids
from app.errors import Conflict, NotFound

_FEED_SELECT = """SELECT f.id, f.folder_id, f.title, f.position, f.url, f.site_url, f.last_fetched_at, f.last_error,
    f.auto_stash, (SELECT COUNT(*) FROM articles a WHERE a.feed_id = f.id AND a.read_at IS NULL) AS unread
    FROM feeds f"""
_STATE_SELECT = "SELECT id, url, etag, last_modified, last_fetched_at FROM feeds"


def _feed(row: sqlite3.Row) -> Feed:
    return Feed(**{**dict(row), "auto_stash": bool(row["auto_stash"])})


def _states(rows) -> list[FeedFetchState]:
    return [FeedFetchState(**dict(row)) for row in rows]


def _position_at_end(conn: sqlite3.Connection, user_id: int, folder_id: int | None) -> int:
    return next_position(conn, "feeds", "user_id = ? AND folder_id IS ?", [user_id, folder_id])


# ------------------------------------------------------------------ reading


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[Feed]:
    rows = conn.execute(f"{_FEED_SELECT} WHERE f.user_id = ? ORDER BY f.position, f.title COLLATE NOCASE", (user_id,))
    return [_feed(row) for row in rows]


def get(conn: sqlite3.Connection, user_id: int, feed_id: int) -> Feed:
    row = conn.execute(f"{_FEED_SELECT} WHERE f.id = ? AND f.user_id = ?", (feed_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Feed not found")
    return _feed(row)


def is_followed(conn: sqlite3.Connection, user_id: int, url: str) -> bool:
    return conn.execute("SELECT 1 FROM feeds WHERE user_id = ? AND url = ?", (user_id, url)).fetchone() is not None


def exists(conn: sqlite3.Connection, feed_id: int) -> bool:
    return conn.execute("SELECT 1 FROM feeds WHERE id = ?", (feed_id,)).fetchone() is not None


# ------------------------------------------------------------------ managing


def create(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    url: str,
    title: str,
    folder_id: int | None = None,
    site_url: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    fetched_at: int | None = None,
) -> int:
    """Adds a feed at the end of its folder. Returns the feed id."""
    title = clean_name(title, "Name")
    if folder_id is not None:
        folders_repo.get(conn, user_id, folder_id)
    return conn.execute(
        """INSERT INTO feeds (user_id, folder_id, url, title, position, site_url, etag, last_modified,
               last_fetched_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, folder_id, url, title, _position_at_end(conn, user_id, folder_id), site_url, etag,
         last_modified, fetched_at, now()),
    ).lastrowid


def rename(conn: sqlite3.Connection, user_id: int, feed_id: int, title: str) -> None:
    get(conn, user_id, feed_id)
    conn.execute("UPDATE feeds SET title = ? WHERE id = ?", (clean_name(title, "Name"), feed_id))


def change_source(
    conn: sqlite3.Connection, user_id: int, feed_id: int, *, url: str, site_url: str | None, etag: str | None,
    last_modified: str | None, fetched_at: int,
) -> None:
    """Points a feed at a new URL that has just been fetched successfully, clearing any old error."""
    get(conn, user_id, feed_id)
    if conn.execute("SELECT 1 FROM feeds WHERE user_id = ? AND url = ? AND id <> ?", (user_id, url, feed_id)).fetchone():
        raise Conflict("You already follow that feed")
    conn.execute(
        """UPDATE feeds SET url = ?, site_url = COALESCE(?, site_url), etag = ?, last_modified = ?,
               last_fetched_at = ?, last_error = NULL WHERE id = ?""",
        (url, site_url, etag, last_modified, fetched_at, feed_id),
    )


def move(conn: sqlite3.Connection, user_id: int, feed_id: int, folder_id: int | None) -> None:
    """Moves a feed to the end of another folder (None = Uncategorized)."""
    feed = get(conn, user_id, feed_id)
    if folder_id == feed.folder_id:
        return
    if folder_id is not None:
        folders_repo.get(conn, user_id, folder_id)
    conn.execute(
        "UPDATE feeds SET folder_id = ?, position = ? WHERE id = ?",
        (folder_id, _position_at_end(conn, user_id, folder_id), feed_id),
    )


def set_auto_stash(conn: sqlite3.Connection, user_id: int, feed_id: int, enabled: bool) -> None:
    """Whether the feed's new articles go straight to the stash (and are marked read)."""
    get(conn, user_id, feed_id)
    conn.execute("UPDATE feeds SET auto_stash = ? WHERE id = ?", (int(enabled), feed_id))


def auto_stash_owner(conn: sqlite3.Connection, feed_id: int) -> int | None:
    """The feed's owner when its new articles go to their stash, otherwise None."""
    row = conn.execute("SELECT user_id FROM feeds WHERE id = ? AND auto_stash = 1", (feed_id,)).fetchone()
    return row["user_id"] if row else None


def delete(conn: sqlite3.Connection, user_id: int, feed_id: int) -> None:
    get(conn, user_id, feed_id)
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))


def reorder(conn: sqlite3.Connection, user_id: int, folder_id: int | None, ids: Sequence[int]) -> list[int]:
    """Sets the order of one folder's feeds. Listed feeds from other folders move into it."""
    if folder_id is not None:
        folders_repo.get(conn, user_id, folder_id)
    owned = {row["id"] for row in conn.execute("SELECT id FROM feeds WHERE user_id = ?", (user_id,))}
    current = [row["id"] for row in conn.execute(
        "SELECT id FROM feeds WHERE user_id = ? AND folder_id IS ? ORDER BY position, title COLLATE NOCASE",
        (user_id, folder_id),
    )]
    order = ordered_ids(current, ids, owned)
    conn.executemany(
        "UPDATE feeds SET folder_id = ?, position = ? WHERE id = ?",
        [(folder_id, position, feed_id) for position, feed_id in enumerate(order)],
    )
    return order


# ------------------------------------------------------------------ fetching


def fetch_states_in_scope(conn: sqlite3.Connection, user_id: int, scope: Scope) -> list[FeedFetchState]:
    if scope.kind == "uncategorized":
        rows = conn.execute(f"{_STATE_SELECT} WHERE user_id = ? AND folder_id IS NULL", (user_id,))
    elif scope.kind == "folder":
        rows = conn.execute(f"{_STATE_SELECT} WHERE user_id = ? AND folder_id = ?", (user_id, scope.id))
    elif scope.kind == "feed":
        rows = conn.execute(f"{_STATE_SELECT} WHERE user_id = ? AND id = ?", (user_id, scope.id))
    else:  # all, starred
        rows = conn.execute(f"{_STATE_SELECT} WHERE user_id = ?", (user_id,))
    return _states(rows)


def due_for_refresh(conn: sqlite3.Connection, *, fetched_before: int) -> list[FeedFetchState]:
    rows = conn.execute(
        f"{_STATE_SELECT} WHERE last_fetched_at IS NULL OR last_fetched_at < ?", (fetched_before,)
    )
    return _states(rows)


def never_fetched(conn: sqlite3.Connection, user_id: int) -> list[FeedFetchState]:
    return _states(conn.execute(f"{_STATE_SELECT} WHERE user_id = ? AND last_fetched_at IS NULL", (user_id,)))


def record_success(
    conn: sqlite3.Connection, feed_id: int, *, fetched_at: int, etag: str | None, last_modified: str | None,
    site_url: str | None,
) -> None:
    conn.execute(
        """UPDATE feeds SET etag = ?, last_modified = ?, last_fetched_at = ?, last_error = NULL,
               site_url = COALESCE(?, site_url) WHERE id = ?""",
        (etag, last_modified, fetched_at, site_url, feed_id),
    )


def record_checked(conn: sqlite3.Connection, feed_id: int, *, fetched_at: int, error: str | None) -> None:
    """Records a fetch that produced nothing new: unchanged (error=None) or failed."""
    conn.execute("UPDATE feeds SET last_fetched_at = ?, last_error = ? WHERE id = ?", (fetched_at, error, feed_id))
