"""Smart lists: saved stash searches (words, a type, a tag and/or a folder), shown in the sidebar."""

import sqlite3

from app.db.models import SmartList
from app.db.repositories import items as items_repo
from app.db.repositories import stash_folders
from app.db.repositories._common import clean_name, next_position
from app.errors import Conflict, InvalidInput, NotFound
from app.text import collapse_whitespace

MAX_QUERY = 500
_SELECT = "SELECT id, name, position, query, type, tag, folder_id FROM smart_lists"
_UNSET = object()


def _list(row: sqlite3.Row) -> SmartList:
    return SmartList(
        id=row["id"], name=row["name"], position=row["position"], query=row["query"], type=row["type"],
        tag=row["tag"], folder_id=row["folder_id"],
    )


def _check_unique(conn: sqlite3.Connection, user_id: int, name: str, list_id: int | None = None) -> None:
    row = conn.execute(
        "SELECT id FROM smart_lists WHERE user_id = ? AND name = ? COLLATE NOCASE", (user_id, name)
    ).fetchone()
    if row and row["id"] != list_id:
        raise Conflict("A smart list with that name already exists")


def _filters(conn: sqlite3.Connection, user_id: int, *, query, type, tag, folder_id) -> tuple:
    query = collapse_whitespace(query)[:MAX_QUERY] or None
    type = type or None
    if type is not None and type not in items_repo.ITEM_TYPES:
        raise InvalidInput(f"type must be one of: {', '.join(items_repo.ITEM_TYPES)}")
    tag = next(iter(items_repo.normalize_tags([tag])), None) if tag else None
    if folder_id is not None:
        stash_folders.get(conn, user_id, folder_id)
    if not (query or type or tag or folder_id):
        raise InvalidInput("A smart list needs something to look for: words, a type, a tag or a folder")
    return query, type, tag, folder_id


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[SmartList]:
    rows = conn.execute(f"{_SELECT} WHERE user_id = ? ORDER BY position, name COLLATE NOCASE", (user_id,))
    return [_list(row) for row in rows]


def get(conn: sqlite3.Connection, user_id: int, list_id: int) -> SmartList:
    row = conn.execute(f"{_SELECT} WHERE id = ? AND user_id = ?", (list_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Smart list not found")
    return _list(row)


def create(
    conn: sqlite3.Connection, user_id: int, *, name: str, query: str | None = None, type: str | None = None,
    tag: str | None = None, folder_id: int | None = None,
) -> SmartList:
    name = clean_name(name, "Name")
    _check_unique(conn, user_id, name)
    filters = _filters(conn, user_id, query=query, type=type, tag=tag, folder_id=folder_id)
    list_id = conn.execute(
        "INSERT INTO smart_lists (user_id, name, position, query, type, tag, folder_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, next_position(conn, "smart_lists", "user_id = ?", [user_id]), *filters),
    ).lastrowid
    return get(conn, user_id, list_id)


def update(
    conn: sqlite3.Connection, user_id: int, list_id: int, *, name=_UNSET, query=_UNSET, type=_UNSET, tag=_UNSET,
    folder_id=_UNSET,
) -> SmartList:
    """Changes only what is passed."""
    current = get(conn, user_id, list_id)
    name = current.name if name is _UNSET else clean_name(name, "Name")
    _check_unique(conn, user_id, name, list_id)
    filters = _filters(
        conn, user_id,
        query=current.query if query is _UNSET else query,
        type=current.type if type is _UNSET else type,
        tag=current.tag if tag is _UNSET else tag,
        folder_id=current.folder_id if folder_id is _UNSET else folder_id,
    )
    conn.execute(
        "UPDATE smart_lists SET name = ?, query = ?, type = ?, tag = ?, folder_id = ? WHERE id = ?",
        (name, *filters, list_id),
    )
    return get(conn, user_id, list_id)


def delete(conn: sqlite3.Connection, user_id: int, list_id: int) -> None:
    get(conn, user_id, list_id)
    conn.execute("DELETE FROM smart_lists WHERE id = ?", (list_id,))
