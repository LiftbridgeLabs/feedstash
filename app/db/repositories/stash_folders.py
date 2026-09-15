"""Folders in the stash, for keeping saved items together by project or topic. An item is in at most one folder."""

import sqlite3
from collections.abc import Sequence

from app.db.models import StashFolder
from app.db.repositories._common import clean_name, next_position, ordered_ids
from app.errors import Conflict, NotFound

_SELECT = """SELECT f.id, f.name, f.position,
    (SELECT COUNT(*) FROM items i WHERE i.folder_id = f.id AND i.archived_at IS NULL) AS count
    FROM stash_folders f"""


def _folder(row: sqlite3.Row) -> StashFolder:
    return StashFolder(id=row["id"], name=row["name"], position=row["position"], count=row["count"])


def _check_unique(conn: sqlite3.Connection, user_id: int, name: str, folder_id: int | None = None) -> None:
    row = conn.execute(
        "SELECT id FROM stash_folders WHERE user_id = ? AND name = ? COLLATE NOCASE", (user_id, name)
    ).fetchone()
    if row and row["id"] != folder_id:
        raise Conflict("A stash folder with that name already exists")


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[StashFolder]:
    rows = conn.execute(f"{_SELECT} WHERE f.user_id = ? ORDER BY f.position, f.name COLLATE NOCASE", (user_id,))
    return [_folder(row) for row in rows]


def get(conn: sqlite3.Connection, user_id: int, folder_id: int) -> StashFolder:
    row = conn.execute(f"{_SELECT} WHERE f.id = ? AND f.user_id = ?", (folder_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Folder not found")
    return _folder(row)


def create(conn: sqlite3.Connection, user_id: int, name: str) -> StashFolder:
    """Appends a folder to the end of the list."""
    name = clean_name(name, "Folder name")
    _check_unique(conn, user_id, name)
    position = next_position(conn, "stash_folders", "user_id = ?", [user_id])
    folder_id = conn.execute(
        "INSERT INTO stash_folders (user_id, name, position) VALUES (?, ?, ?)", (user_id, name, position)
    ).lastrowid
    return get(conn, user_id, folder_id)


def rename(conn: sqlite3.Connection, user_id: int, folder_id: int, name: str) -> StashFolder:
    name = clean_name(name, "Folder name")
    get(conn, user_id, folder_id)
    _check_unique(conn, user_id, name, folder_id)
    conn.execute("UPDATE stash_folders SET name = ? WHERE id = ?", (name, folder_id))
    return get(conn, user_id, folder_id)


def delete(conn: sqlite3.Connection, user_id: int, folder_id: int) -> None:
    """Deletes a folder. Its items stay in the stash, in no folder; smart lists of the folder go with it."""
    get(conn, user_id, folder_id)
    conn.execute("DELETE FROM stash_folders WHERE id = ?", (folder_id,))


def reorder(conn: sqlite3.Connection, user_id: int, ids: Sequence[int]) -> list[int]:
    current = [row["id"] for row in conn.execute(
        "SELECT id FROM stash_folders WHERE user_id = ? ORDER BY position, name COLLATE NOCASE", (user_id,)
    )]
    order = ordered_ids(current, ids, set(current))
    conn.executemany("UPDATE stash_folders SET position = ? WHERE id = ?", list(enumerate(order)))
    return order
