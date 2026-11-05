"""Moving an account between FeedStash servers: everything one account owns, as plain data, and adding such data to
an account. Ids in the data are only the export's own, mapped to new ones on import.

Imports merge: a feed already followed (by address), a folder or stash folder or tag of the same name, an article
already there (by feed and guid), a smart list of the same name, a stash item saved at the same moment with the same
address or text, are all kept once. The data comes from a file someone uploaded, so every value is checked.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.db.repositories import feeds as feeds_repo
from app.db.repositories import folders as folders_repo
from app.db.repositories import muted_words as muted_words_repo
from app.db.repositories import search as search_index
from app.db.repositories import stash_folders as stash_folders_repo
from app.db.repositories.items import ITEM_TYPES, normalize_tags
from app.errors import InvalidInput
from app.text import html_to_text

FORMAT = "feedstash-account"
VERSION = 1


# ------------------------------------------------------------------ export


def _rows(conn: sqlite3.Connection, sql: str, *params: Any) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params)]


def export(conn: sqlite3.Connection, user_id: int) -> dict:
    """Everything the account owns. Not: its password, tokens, sessions, mailbox login, or anything server-wide."""
    account = conn.execute("SELECT name, read_retention_days, sections FROM users WHERE id = ?", (user_id,)).fetchone()
    items = _rows(conn, """SELECT id, type, title, content, url, image_name, source, reviewed_at, archived_at,
        created_at, updated_at, folder_id, feed_id FROM items WHERE user_id = ? ORDER BY id""", user_id)
    by_item = {item["id"]: item for item in items}
    for item in items:
        item.update(tags=[], links=[], images=[], page=None)
    for row in conn.execute("""SELECT it.item_id, t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id
            JOIN items i ON i.id = it.item_id WHERE i.user_id = ? ORDER BY t.name""", (user_id,)):
        by_item[row["item_id"]]["tags"].append(row["name"])
    for row in conn.execute("""SELECT l.item_id, l.url, l.label FROM item_links l JOIN items i ON i.id = l.item_id
            WHERE i.user_id = ? ORDER BY l.item_id, l.position""", (user_id,)):
        by_item[row["item_id"]]["links"].append({"url": row["url"], "label": row["label"]})
    for row in conn.execute("""SELECT m.item_id, m.image_name FROM item_images m JOIN items i ON i.id = m.item_id
            WHERE i.user_id = ? ORDER BY m.item_id, m.position""", (user_id,)):
        by_item[row["item_id"]]["images"].append(row["image_name"])
    for row in conn.execute("""SELECT p.item_id, p.url, p.status, p.fetched_at, p.title, p.description, p.image_url,
            p.site_name, p.text, p.html FROM item_pages p JOIN items i ON i.id = p.item_id WHERE i.user_id = ?""",
                            (user_id,)):
        page = dict(row)
        by_item[page.pop("item_id")]["page"] = page
    return {
        "format": FORMAT,
        "version": VERSION,
        "account": dict(account) if account else {},
        "folders": _rows(conn, "SELECT id, name, position FROM folders WHERE user_id = ? ORDER BY position, id", user_id),
        "feeds": _rows(conn, """SELECT id, folder_id, url, title, site_url, position, auto_stash, full_text,
            open_website, created_at FROM feeds WHERE user_id = ? ORDER BY position, id""", user_id),
        "articles": _rows(conn, """SELECT a.feed_id, a.guid, a.title, a.url, a.author, a.summary, a.content, a.image,
            a.published_at, a.fetched_at, a.read_at, a.starred_at, a.full_content, a.full_status
            FROM articles a JOIN feeds f ON f.id = a.feed_id WHERE f.user_id = ? ORDER BY a.id""", user_id),
        "purged_articles": _rows(conn, """SELECT p.feed_id, p.guid, p.published_at FROM purged_articles p
            JOIN feeds f ON f.id = p.feed_id WHERE f.user_id = ?""", user_id),
        "stash_folders": _rows(conn, "SELECT id, name, position FROM stash_folders WHERE user_id = ? ORDER BY position, id", user_id),
        "items": items,
        "smart_lists": _rows(conn, """SELECT name, position, query, type, tag, folder_id FROM smart_lists
            WHERE user_id = ? ORDER BY position, id""", user_id),
        "stash_rules": _rows(conn, """SELECT position, field, value, add_tag, folder_id, mark_reviewed, archive, created_at
            FROM stash_rules WHERE user_id = ? ORDER BY position, id""", user_id),
        "muted_words": _rows(conn, """SELECT phrase, title_only, folder_id, feed_id, created_at FROM muted_words
            WHERE user_id = ? ORDER BY id""", user_id),
    }


def image_names(data: dict) -> set[str]:
    """Every uploaded picture the exported items use."""
    names = set()
    for item in _list(data, "items"):
        names.update(name for name in _values(item, "images") if isinstance(name, str))
        if isinstance(item.get("image_name"), str):
            names.add(item["image_name"])
    return names


# ------------------------------------------------------------------ import


@dataclass
class ImportCounts:
    folders: int = 0
    feeds: int = 0
    articles: int = 0
    stash_folders: int = 0
    items: int = 0
    smart_lists: int = 0
    stash_rules: int = 0
    muted_words: int = 0
    skipped: list[str] = field(default_factory=list)  # what couldn't be brought in, in words


def _text(value: Any, limit: int = 2000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value[:limit]


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _values(entry: dict, key: str) -> list:
    """A list field of one entry (an item's tags, links or pictures): empty when missing or not a list."""
    value = entry.get(key)
    return value if isinstance(value, list) else []


def _list(data: dict, key: str) -> list[dict]:
    value = data.get(key) or []
    if not isinstance(value, list):
        raise InvalidInput(f"This file isn't a FeedStash export ({key} isn't a list)")
    return [entry for entry in value if isinstance(entry, dict)]


def check(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise InvalidInput("This file isn't a FeedStash export. Make one with Settings → You → Download everything.")
    if _int(data.get("version")) != VERSION:
        raise InvalidInput("This export comes from a newer FeedStash. Update this server, then try again.")
    return data


def import_into(
    conn: sqlite3.Connection, user_id: int, data: dict, *, now: int, image_for: Callable[[str], str | None],
) -> ImportCounts:
    """Adds an export to the account. `image_for` turns an exported picture name into the name it was stored under
    here (None when the file didn't have it, or it wasn't a real image)."""
    data = check(data)
    counts = ImportCounts()

    folders: dict[int, int] = {}
    for entry in _list(data, "folders"):
        name = _text(entry.get("name"), 200)
        if name and (export_id := _int(entry.get("id"))) is not None:
            existed = folders_repo.find_by_name(conn, user_id, name)
            folders[export_id] = (existed or folders_repo.get_or_create(conn, user_id, name)).id
            counts.folders += existed is None

    feeds: dict[int, int] = {}
    for entry in _list(data, "feeds"):
        url, export_id = _text(entry.get("url")), _int(entry.get("id"))
        if not url or export_id is None:
            continue
        existing = conn.execute("SELECT id FROM feeds WHERE user_id = ? AND url = ?", (user_id, url)).fetchone()
        if existing:
            feeds[export_id] = existing["id"]
            continue
        try:
            feed_id = feeds_repo.create(
                conn, user_id, url=url, title=_text(entry.get("title"), 200) or url,
                folder_id=folders.get(_int(entry.get("folder_id"))), site_url=_text(entry.get("site_url")),
            )
        except InvalidInput as exc:
            counts.skipped.append(f"Feed {url}: {exc}")
            continue
        conn.execute(
            "UPDATE feeds SET auto_stash = ?, full_text = ?, open_website = ? WHERE id = ? AND user_id = ?",
            (int(bool(entry.get("auto_stash"))), int(bool(entry.get("full_text"))), int(bool(entry.get("open_website"))),
             feed_id, user_id),
        )
        feeds[export_id] = feed_id
        counts.feeds += 1

    for entry in _list(data, "articles"):
        feed_id, guid = feeds.get(_int(entry.get("feed_id"))), _text(entry.get("guid"), 2000)
        if feed_id is None or not guid:
            continue
        published = _int(entry.get("published_at")) or now
        cursor = conn.execute(
            """INSERT OR IGNORE INTO articles (feed_id, guid, title, url, author, summary, content, image, published_at,
                   fetched_at, read_at, starred_at, full_content, full_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (feed_id, guid, _text(entry.get("title"), 1000) or "", _text(entry.get("url")), _text(entry.get("author"), 500),
             _text(entry.get("summary"), 100_000), _text(entry.get("content"), 2_000_000), _text(entry.get("image")),
             published, _int(entry.get("fetched_at")) or now, _int(entry.get("read_at")), _int(entry.get("starred_at")),
             _text(entry.get("full_content"), 2_000_000), _text(entry.get("full_status"), 20)),
        )
        if cursor.rowcount == 1:
            search_index.index_article(conn, cursor.lastrowid, _text(entry.get("title"), 1000) or "",
                                       html_to_text(_text(entry.get("content"), 2_000_000) or _text(entry.get("summary"), 100_000) or ""))
            counts.articles += 1

    for entry in _list(data, "purged_articles"):
        feed_id, guid = feeds.get(_int(entry.get("feed_id"))), _text(entry.get("guid"), 2000)
        if feed_id is not None and guid:
            conn.execute("INSERT OR IGNORE INTO purged_articles (feed_id, guid, published_at) VALUES (?, ?, ?)",
                         (feed_id, guid, _int(entry.get("published_at")) or 0))

    stash_folders: dict[int, int] = {}
    for entry in _list(data, "stash_folders"):
        name = _text(entry.get("name"), 200)
        if name and (export_id := _int(entry.get("id"))) is not None:
            existed = stash_folders_repo.find_by_name(conn, user_id, name)
            stash_folders[export_id] = (existed or stash_folders_repo.get_or_create(conn, user_id, name)).id
            counts.stash_folders += existed is None

    for entry in _list(data, "items"):
        if _import_item(conn, user_id, entry, now=now, stash_folders=stash_folders, feeds=feeds, image_for=image_for,
                        skipped=counts.skipped):
            counts.items += 1
    conn.execute("DELETE FROM tags WHERE user_id = ? AND NOT EXISTS (SELECT 1 FROM item_tags it WHERE it.tag_id = tags.id)",
                 (user_id,))

    for entry in _list(data, "smart_lists"):
        name = _text(entry.get("name"), 200)
        if not name or conn.execute("SELECT 1 FROM smart_lists WHERE user_id = ? AND name = ?", (user_id, name)).fetchone():
            continue
        conn.execute(
            "INSERT INTO smart_lists (user_id, name, position, query, type, tag, folder_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, _int(entry.get("position")) or 0, _text(entry.get("query"), 500),
             entry.get("type") if entry.get("type") in ITEM_TYPES else None, _text(entry.get("tag"), 100),
             stash_folders.get(_int(entry.get("folder_id")))),
        )
        counts.smart_lists += 1

    for entry in _list(data, "stash_rules"):
        rule = (_text(entry.get("field"), 20), _text(entry.get("value"), 500), _text(entry.get("add_tag"), 100),
                stash_folders.get(_int(entry.get("folder_id"))), int(bool(entry.get("mark_reviewed"))),
                int(bool(entry.get("archive"))))
        if not rule[0] or not rule[1] or conn.execute(
            """SELECT 1 FROM stash_rules WHERE user_id = ? AND field = ? AND value = ? AND add_tag IS ?
               AND folder_id IS ? AND mark_reviewed = ? AND archive = ?""", (user_id, *rule)
        ).fetchone():
            continue
        conn.execute(
            """INSERT INTO stash_rules (user_id, position, field, value, add_tag, folder_id, mark_reviewed, archive,
                   created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, _int(entry.get("position")) or 0, *rule, _int(entry.get("created_at")) or now),
        )
        counts.stash_rules += 1

    for entry in _list(data, "muted_words"):
        phrase = " ".join((_text(entry.get("phrase"), 200) or "").split())  # stored cleaned, as Settings saves it
        folder_id, feed_id = folders.get(_int(entry.get("folder_id"))), feeds.get(_int(entry.get("feed_id")))
        if not phrase or (entry.get("folder_id") is not None and folder_id is None) or (
                entry.get("feed_id") is not None and feed_id is None):
            continue
        before = conn.execute("SELECT COUNT(*) FROM muted_words WHERE user_id = ?", (user_id,)).fetchone()[0]
        try:
            muted_words_repo.create(conn, user_id, phrase=phrase, title_only=bool(entry.get("title_only", True)),
                                    folder_id=folder_id, feed_id=feed_id, now=now)
        except InvalidInput:
            continue
        counts.muted_words += conn.execute("SELECT COUNT(*) FROM muted_words WHERE user_id = ?", (user_id,)).fetchone()[0] > before

    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    if (days := _int(account.get("read_retention_days"))) is not None and 0 <= days <= 3650:  # 0: only the server's own cleanup
        conn.execute("UPDATE users SET read_retention_days = ? WHERE id = ?", (days, user_id))
    if account.get("sections") in ("both", "feeds", "stash"):
        conn.execute("UPDATE users SET sections = ? WHERE id = ?", (account["sections"], user_id))
    return counts


def _import_item(
    conn: sqlite3.Connection, user_id: int, entry: dict, *, now: int, stash_folders: dict[int, int],
    feeds: dict[int, int], image_for: Callable[[str], str | None], skipped: list[str],
) -> bool:
    kind = entry.get("type")
    if kind not in ITEM_TYPES:
        return False
    created = _int(entry.get("created_at")) or now
    title, content, url = _text(entry.get("title"), 1000), _text(entry.get("content"), 200_000), _text(entry.get("url"))
    # The same item saved at the same moment is already here (an export brought in twice).
    if conn.execute(
        """SELECT 1 FROM items WHERE user_id = ? AND created_at = ? AND url IS ? AND title IS ? AND content IS ?""",
        (user_id, created, url, title, content),
    ).fetchone():
        return False
    names = []
    for name in [n for n in _values(entry, "images") if isinstance(n, str)][:20]:
        stored = image_for(name)
        if stored:
            names.append(stored)
        else:
            skipped.append(f"A picture of \"{title or url or 'a stash item'}\" wasn't in the file")
    item_id = conn.execute(
        """INSERT INTO items (user_id, type, title, content, url, image_name, source, reviewed_at, archived_at,
               created_at, updated_at, folder_id, feed_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, kind, title, content, url, names[0] if names else None, _text(entry.get("source"), 100) or "import",
         _int(entry.get("reviewed_at")), _int(entry.get("archived_at")), created, _int(entry.get("updated_at")) or created,
         stash_folders.get(_int(entry.get("folder_id"))), feeds.get(_int(entry.get("feed_id")))),
    ).lastrowid
    for name in normalize_tags([t for t in _values(entry, "tags") if isinstance(t, str)]):
        conn.execute("INSERT OR IGNORE INTO tags (user_id, name) VALUES (?, ?)", (user_id, name))
        tag_id = conn.execute("SELECT id FROM tags WHERE user_id = ? AND name = ?", (user_id, name)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)", (item_id, tag_id))
    links = [link for link in _values(entry, "links") if isinstance(link, dict) and _text(link.get("url"))]
    conn.executemany(
        "INSERT INTO item_links (item_id, url, label, position) VALUES (?, ?, ?, ?)",
        [(item_id, _text(link["url"]), _text(link.get("label"), 200), position) for position, link in enumerate(links[:50])],
    )
    conn.executemany(
        "INSERT INTO item_images (item_id, position, image_name) VALUES (?, ?, ?)",
        [(item_id, position, name) for position, name in enumerate(names)],
    )
    page = entry.get("page") if isinstance(entry.get("page"), dict) else None
    if page and _text(page.get("url")):
        done = page.get("status") in ("ready", "skipped", "failed")  # anything else is fetched again here
        conn.execute(
            """INSERT INTO item_pages (item_id, url, status, fetched_at, title, description, image_url, site_name, text, html)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, _text(page["url"]), page["status"] if done else "pending", _int(page.get("fetched_at")),
             _text(page.get("title"), 1000), _text(page.get("description"), 5000), _text(page.get("image_url")),
             _text(page.get("site_name"), 200), _text(page.get("text"), 2_000_000), _text(page.get("html"), 5_000_000)),
        )
    search_index.index_item(conn, item_id)
    return True
