"""Stash items (links, snippets, screenshots, emails) and their tags."""

import sqlite3
from collections.abc import Iterable, Sequence

from app.db.models import ItemFilter, ItemLink, StashItem, StashSummary, TagCount
from app.errors import InvalidInput, NotFound

ITEM_TYPES = ("link", "snippet", "screenshot", "email")
MAX_PAGE_SIZE = 200
MAX_TAG_LENGTH = 50

_SELECT = """SELECT i.id, i.type, i.title, i.content, i.url, i.image_name, i.source, i.reviewed_at, i.archived_at,
    i.created_at, i.updated_at FROM items i"""
_UNSET = object()


def normalize_tags(raw: Iterable[str]) -> list[str]:
    """Lowercase, whitespace-squeezed, without a leading '#', de-duplicated, in the order given."""
    seen: set[str] = set()
    tags = []
    for value in raw:
        name = " ".join(str(value).split()).lower().lstrip("#").strip()[:MAX_TAG_LENGTH]
        if name and name not in seen:
            seen.add(name)
            tags.append(name)
    return tags


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tags_by_item(conn: sqlite3.Connection, item_ids: Sequence[int]) -> dict[int, list[str]]:
    tags: dict[int, list[str]] = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return tags
    rows = conn.execute(
        f"""SELECT it.item_id, t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id
            WHERE it.item_id IN ({','.join('?' * len(item_ids))}) ORDER BY t.name""",
        list(item_ids),
    )
    for row in rows:
        tags[row["item_id"]].append(row["name"])
    return tags


def _links_by_item(conn: sqlite3.Connection, item_ids: Sequence[int]) -> dict[int, list[ItemLink]]:
    links: dict[int, list[ItemLink]] = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return links
    rows = conn.execute(
        f"""SELECT id, item_id, url, label FROM item_links
            WHERE item_id IN ({','.join('?' * len(item_ids))}) ORDER BY position, id""",
        list(item_ids),
    )
    for row in rows:
        links[row["item_id"]].append(ItemLink(url=row["url"], label=row["label"], id=row["id"]))
    return links


def _items(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[StashItem]:
    ids = [row["id"] for row in rows]
    tags, links = _tags_by_item(conn, ids), _links_by_item(conn, ids)
    return [
        StashItem(
            id=row["id"], type=row["type"], title=row["title"], content=row["content"], url=row["url"],
            image_name=row["image_name"], source=row["source"], reviewed=row["reviewed_at"] is not None,
            archived=row["archived_at"] is not None, created_at=row["created_at"], updated_at=row["updated_at"],
            tags=tags[row["id"]], links=links[row["id"]],
        )
        for row in rows
    ]


def with_primary(url: str | None, links: Iterable[ItemLink]) -> list[ItemLink]:
    """The complete link list: `links`, with `url` (what single-URL clients send) first unless it's already there."""
    result = [link for link in links if link.url]
    if url and all(link.url != url for link in result):
        result.insert(0, ItemLink(url=url))
    return result


def _set_links(conn: sqlite3.Connection, item_id: int, links: Sequence[ItemLink]) -> None:
    conn.execute("DELETE FROM item_links WHERE item_id = ?", (item_id,))
    conn.executemany(
        "INSERT INTO item_links (item_id, url, label, position) VALUES (?, ?, ?, ?)",
        [(item_id, link.url, link.label, position) for position, link in enumerate(links)],
    )


def _set_tags(conn: sqlite3.Connection, user_id: int, item_id: int, tags: Iterable[str]) -> None:
    conn.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
    for name in normalize_tags(tags):
        conn.execute("INSERT OR IGNORE INTO tags (user_id, name) VALUES (?, ?)", (user_id, name))
        tag_id = conn.execute("SELECT id FROM tags WHERE user_id = ? AND name = ?", (user_id, name)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)", (item_id, tag_id))
    _drop_unused_tags(conn, user_id)


def _drop_unused_tags(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute(
        "DELETE FROM tags WHERE user_id = ? AND NOT EXISTS (SELECT 1 FROM item_tags it WHERE it.tag_id = tags.id)",
        (user_id,),
    )


# ------------------------------------------------------------------ reading


def get(conn: sqlite3.Connection, user_id: int, item_id: int) -> StashItem:
    rows = conn.execute(f"{_SELECT} WHERE i.id = ? AND i.user_id = ?", (item_id, user_id)).fetchall()
    if not rows:
        raise NotFound("Not found")
    return _items(conn, rows)[0]


def search(conn: sqlite3.Connection, user_id: int, criteria: ItemFilter) -> list[StashItem]:
    """Newest first. Archived items are only returned when asked for."""
    where, params = ["i.user_id = ?"], [user_id]
    if criteria.type:
        where.append("i.type = ?")
        params.append(criteria.type)
    if criteria.tag:
        where.append(
            "EXISTS (SELECT 1 FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_id = i.id AND t.name = ?)"
        )
        params.append(criteria.tag.strip().lower())
    if criteria.reviewed is not None:
        where.append("i.reviewed_at IS NOT NULL" if criteria.reviewed else "i.reviewed_at IS NULL")
    where.append("i.archived_at IS NOT NULL" if criteria.archived else "i.archived_at IS NULL")
    if criteria.query:
        pattern = f"%{_escape_like(criteria.query)}%"
        where.append(
            "(i.title LIKE ? ESCAPE '\\' OR i.content LIKE ? ESCAPE '\\' OR i.url LIKE ? ESCAPE '\\' OR EXISTS ("
            "SELECT 1 FROM item_links l WHERE l.item_id = i.id AND (l.url LIKE ? ESCAPE '\\' OR l.label LIKE ? ESCAPE '\\')))"
        )
        params += [pattern] * 5
    limit = max(1, min(criteria.limit, MAX_PAGE_SIZE))
    rows = conn.execute(
        f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY i.created_at DESC, i.id DESC LIMIT ? OFFSET ?",
        [*params, limit, max(0, criteria.offset)],
    ).fetchall()
    return _items(conn, rows)


def find_link(conn: sqlite3.Connection, user_id: int, url: str) -> StashItem | None:
    rows = conn.execute(
        f"{_SELECT} WHERE i.user_id = ? AND i.type = 'link' AND i.url = ? AND i.archived_at IS NULL "
        "ORDER BY i.id DESC LIMIT 1",
        (user_id, url),
    ).fetchall()
    return _items(conn, rows)[0] if rows else None


def tag_counts(conn: sqlite3.Connection, user_id: int) -> list[TagCount]:
    """Tags on at least one active (non-archived) item, with how many."""
    rows = conn.execute(
        """SELECT t.name, COUNT(*) AS count FROM tags t
               JOIN item_tags it ON it.tag_id = t.id
               JOIN items i ON i.id = it.item_id AND i.archived_at IS NULL
           WHERE t.user_id = ? GROUP BY t.id ORDER BY count DESC, t.name""",
        (user_id,),
    )
    return [TagCount(name=row["name"], count=row["count"]) for row in rows]


def summary(conn: sqlite3.Connection, user_id: int) -> StashSummary:
    by_type = dict.fromkeys(ITEM_TYPES, 0)
    inbox = total = 0
    rows = conn.execute(
        """SELECT type, COUNT(*) AS items, SUM(reviewed_at IS NULL) AS unreviewed FROM items
           WHERE user_id = ? AND archived_at IS NULL GROUP BY type""",
        (user_id,),
    )
    for row in rows:
        by_type[row["type"]] = row["items"]
        total += row["items"]
        inbox += row["unreviewed"]
    archived = conn.execute(
        "SELECT COUNT(*) FROM items WHERE user_id = ? AND archived_at IS NOT NULL", (user_id,)
    ).fetchone()[0]
    return StashSummary(inbox=inbox, total=total, archived=archived, by_type=by_type)


# ------------------------------------------------------------------ writing


def create(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    type: str,
    title: str | None,
    content: str | None,
    url: str | None,
    image_name: str | None,
    source: str,
    tags: Iterable[str],
    now: int,
    links: Iterable[ItemLink] = (),
    reviewed: bool = False,
    archived: bool = False,
) -> StashItem:
    """`url` is folded in as the first link when it isn't among `links`; items.url always mirrors the first link."""
    if type not in ITEM_TYPES:
        raise InvalidInput(f"type must be one of: {', '.join(ITEM_TYPES)}")
    links = with_primary(url, links)
    item_id = conn.execute(
        """INSERT INTO items (user_id, type, title, content, url, image_name, source, reviewed_at, archived_at,
               created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, type, title, content, links[0].url if links else None, image_name, source,
         now if reviewed else None, now if archived else None, now, now),
    ).lastrowid
    _set_tags(conn, user_id, item_id, tags)
    _set_links(conn, item_id, links)
    return get(conn, user_id, item_id)


def update(
    conn: sqlite3.Connection,
    user_id: int,
    item_id: int,
    *,
    now: int,
    title=_UNSET,
    content=_UNSET,
    url=_UNSET,
    reviewed: bool | None = None,
    archived: bool | None = None,
    tags: Iterable[str] | None = None,
    links: Iterable[ItemLink] | None = None,
) -> StashItem:
    """Changes only what is passed. Re-marking an item reviewed or archived keeps the original time.

    `links` replaces the whole list. `url` on its own swaps the primary (first) link and keeps the rest.
    """
    current = get(conn, user_id, item_id)
    new_links = None
    if links is not None:
        new_links = [link for link in links if link.url]
    elif url is not _UNSET:
        rest = current.links[1:]
        if not url:
            new_links = rest
        elif current.links and current.links[0].url == url:
            new_links = current.links
        else:
            new_links = [ItemLink(url=url), *rest]
    if new_links is not None:
        url = new_links[0].url if new_links else None
    sets, params = [], []
    for column, value in (("title", title), ("content", content), ("url", url)):
        if value is not _UNSET:
            sets.append(f"{column} = ?")
            params.append(value)
    for column, flag in (("reviewed_at", reviewed), ("archived_at", archived)):
        if flag is not None:
            sets.append(f"{column} = CASE WHEN ? THEN COALESCE({column}, ?) ELSE NULL END")
            params += [int(flag), now]
    if sets or tags is not None:
        sets.append("updated_at = ?")
        params.append(now)
        conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", [*params, item_id])
    if tags is not None:
        _set_tags(conn, user_id, item_id, tags)
    if new_links is not None:
        _set_links(conn, item_id, new_links)
    return get(conn, user_id, item_id)


def image_names_for_user(conn: sqlite3.Connection, user_id: int) -> list[str]:
    rows = conn.execute("SELECT image_name FROM items WHERE user_id = ? AND image_name IS NOT NULL", (user_id,))
    return [row[0] for row in rows]


def delete(conn: sqlite3.Connection, user_id: int, item_id: int) -> str | None:
    """Deletes an item. Returns its image name so the caller can remove the file."""
    item = get(conn, user_id, item_id)
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    _drop_unused_tags(conn, user_id)
    return item.image_name
