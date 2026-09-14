import sqlite3
from collections.abc import Sequence

from app.db.models import Folder
from app.db.repositories._common import clean_name, next_position, ordered_ids
from app.errors import Conflict, NotFound

_SELECT = "SELECT id, name, position FROM folders"


def _folder(row: sqlite3.Row) -> Folder:
    return Folder(id=row["id"], name=row["name"], position=row["position"])


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[Folder]:
    rows = conn.execute(f"{_SELECT} WHERE user_id = ? ORDER BY position, name COLLATE NOCASE", (user_id,))
    return [_folder(row) for row in rows]


def get(conn: sqlite3.Connection, user_id: int, folder_id: int) -> Folder:
    row = conn.execute(f"{_SELECT} WHERE id = ? AND user_id = ?", (folder_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Folder not found")
    return _folder(row)


def find_by_name(conn: sqlite3.Connection, user_id: int, name: str) -> Folder | None:
    row = conn.execute(f"{_SELECT} WHERE user_id = ? AND name = ?", (user_id, name)).fetchone()
    return _folder(row) if row else None


def names(conn: sqlite3.Connection, user_id: int) -> set[str]:
    return {row["name"] for row in conn.execute("SELECT name FROM folders WHERE user_id = ?", (user_id,))}


def create(conn: sqlite3.Connection, user_id: int, name: str) -> Folder:
    """Appends a new folder to the end of the list."""
    name = clean_name(name, "Folder name")
    if find_by_name(conn, user_id, name):
        raise Conflict("A folder with that name already exists")
    position = next_position(conn, "folders", "user_id = ?", [user_id])
    folder_id = conn.execute(
        "INSERT INTO folders (user_id, name, position) VALUES (?, ?, ?)", (user_id, name, position)
    ).lastrowid
    return Folder(id=folder_id, name=name, position=position)


def get_or_create(conn: sqlite3.Connection, user_id: int, name: str) -> Folder:
    name = clean_name(name, "Folder name")
    return find_by_name(conn, user_id, name) or create(conn, user_id, name)


def rename(conn: sqlite3.Connection, user_id: int, folder_id: int, name: str) -> Folder:
    name = clean_name(name, "Folder name")
    folder = get(conn, user_id, folder_id)
    clash = find_by_name(conn, user_id, name)
    if clash and clash.id != folder_id:
        raise Conflict("A folder with that name already exists")
    conn.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id))
    return Folder(id=folder.id, name=name, position=folder.position)


def delete(conn: sqlite3.Connection, user_id: int, folder_id: int, *, unfollow_feeds: bool) -> None:
    """Deletes a folder. Its feeds are unfollowed, or kept together (in order) at the end of Uncategorized."""
    get(conn, user_id, folder_id)
    if unfollow_feeds:
        conn.execute("DELETE FROM feeds WHERE folder_id = ? AND user_id = ?", (folder_id, user_id))
    else:
        start = next_position(conn, "feeds", "user_id = ? AND folder_id IS NULL", [user_id])
        moving = [row["id"] for row in conn.execute(
            "SELECT id FROM feeds WHERE folder_id = ? ORDER BY position, title COLLATE NOCASE", (folder_id,)
        )]
        conn.executemany(
            "UPDATE feeds SET folder_id = NULL, position = ? WHERE id = ?",
            [(start + offset, feed_id) for offset, feed_id in enumerate(moving)],
        )
    conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))


def reorder(conn: sqlite3.Connection, user_id: int, ids: Sequence[int]) -> list[int]:
    current = [row["id"] for row in conn.execute(
        "SELECT id FROM folders WHERE user_id = ? ORDER BY position, name COLLATE NOCASE", (user_id,)
    )]
    order = ordered_ids(current, ids, set(current))
    conn.executemany("UPDATE folders SET position = ? WHERE id = ?", list(enumerate(order)))
    return order
