"""Rules that sort new stash items: when an item matches, tag it, file it in a folder, mark it reviewed or archive it.

Rules run when something new lands in the stash (from the web app, the clients, or a feed), and on request over
everything saved. Bulk imports don't run them: an import already says where its links go.
"""

import sqlite3
from urllib.parse import urlsplit

from app.db.models import StashItem, StashRule
from app.db.repositories import items as items_repo
from app.db.repositories import stash_folders
from app.db.repositories._common import next_position
from app.errors import InvalidInput, NotFound

FIELDS = ("domain", "url", "title", "text", "feed", "type")
MAX_VALUE = 500
_SELECT = "SELECT id, field, value, add_tag, folder_id, mark_reviewed, archive FROM stash_rules"


def _rule(row: sqlite3.Row) -> StashRule:
    return StashRule(
        id=row["id"], field=row["field"], value=row["value"], add_tag=row["add_tag"], folder_id=row["folder_id"],
        mark_reviewed=bool(row["mark_reviewed"]), archive=bool(row["archive"]),
    )


def _host(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _domain(value: str) -> str:
    """"https://www.Example.com/page", "www.example.com" and "example.com" all mean example.com."""
    value = value.strip().lower()
    if "://" not in value:
        value = f"http://{value}"
    return _host(value)


# ------------------------------------------------------------------ matching (no database)


def matches(rule: StashRule, item: StashItem) -> bool:
    value = rule.value.lower()
    urls = [link.url for link in item.links] or ([item.url] if item.url else [])
    match rule.field:
        case "domain":
            return any(host == value or host.endswith(f".{value}") for host in map(_host, urls))
        case "url":
            return any(value in url.lower() for url in urls)
        case "title":
            return value in (item.title or "").lower()
        case "text":
            labels = " ".join(link.label or "" for link in item.links)
            return value in f"{item.title or ''}\n{item.content or ''}\n{labels}".lower()
        case "feed":
            return item.feed_id is not None and str(item.feed_id) == rule.value
        case "type":
            return item.type == value
    return False


# ------------------------------------------------------------------ storing


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[StashRule]:
    return [_rule(row) for row in conn.execute(f"{_SELECT} WHERE user_id = ? ORDER BY position, id", (user_id,))]


def get(conn: sqlite3.Connection, user_id: int, rule_id: int) -> StashRule:
    row = conn.execute(f"{_SELECT} WHERE id = ? AND user_id = ?", (rule_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Rule not found")
    return _rule(row)


def create(
    conn: sqlite3.Connection, user_id: int, *, field: str, value: str, add_tag: str | None = None,
    folder_id: int | None = None, mark_reviewed: bool = False, archive: bool = False, now: int,
) -> StashRule:
    """Adds a rule after the others. Rules run in order; the first one to choose a folder wins."""
    if field not in FIELDS:
        raise InvalidInput(f"field must be one of: {', '.join(FIELDS)}")
    value = " ".join(str(value or "").split())[:MAX_VALUE]
    if field == "domain":
        value = _domain(value)
    if not value:
        raise InvalidInput("Say what the rule looks for")
    if field == "type" and value not in items_repo.ITEM_TYPES:
        raise InvalidInput(f"type must be one of: {', '.join(items_repo.ITEM_TYPES)}")
    if field == "feed" and not (value.isdigit() and conn.execute(
        "SELECT 1 FROM feeds WHERE id = ? AND user_id = ?", (int(value), user_id)
    ).fetchone()):
        raise InvalidInput("Choose one of the feeds you follow")
    add_tag = next(iter(items_repo.normalize_tags([add_tag])), None) if add_tag else None
    if folder_id is not None:
        stash_folders.get(conn, user_id, folder_id)
    if not (add_tag or folder_id or mark_reviewed or archive):
        raise InvalidInput("Choose what the rule does: add a tag, file in a folder, mark reviewed or archive")
    rule_id = conn.execute(
        """INSERT INTO stash_rules (user_id, position, field, value, add_tag, folder_id, mark_reviewed, archive,
               created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, next_position(conn, "stash_rules", "user_id = ?", [user_id]), field, value, add_tag, folder_id,
         int(mark_reviewed), int(archive), now),
    ).lastrowid
    return get(conn, user_id, rule_id)


def delete(conn: sqlite3.Connection, user_id: int, rule_id: int) -> None:
    get(conn, user_id, rule_id)
    conn.execute("DELETE FROM stash_rules WHERE id = ?", (rule_id,))


# ------------------------------------------------------------------ applying


def apply(
    conn: sqlite3.Connection, user_id: int, item_id: int, *, now: int, rules: list[StashRule] | None = None
) -> bool:
    """Runs the user's rules on one item. Only adds: tags are added, a folder is chosen only for an item in none, and
    items are marked reviewed or archived but never the reverse. Returns whether anything changed."""
    rules = list_for_user(conn, user_id) if rules is None else rules
    if not rules:
        return False
    item = items_repo.get(conn, user_id, item_id)
    tags, folder_id, reviewed, archived = list(item.tags), item.folder_id, item.reviewed, item.archived
    for rule in rules:
        if not matches(rule, item):
            continue
        if rule.add_tag and rule.add_tag not in tags:
            tags.append(rule.add_tag)
        if rule.folder_id and folder_id is None:
            folder_id = rule.folder_id
        reviewed = reviewed or rule.mark_reviewed
        archived = archived or rule.archive
    changes: dict = {}
    if tags != item.tags:
        changes["tags"] = tags
    if folder_id != item.folder_id:
        changes["folder_id"] = folder_id
    if reviewed != item.reviewed:
        changes["reviewed"] = reviewed
    if archived != item.archived:
        changes["archived"] = archived
    if changes:
        items_repo.update(conn, user_id, item_id, now=now, **changes)
    return bool(changes)


def unarchived_item_ids(conn: sqlite3.Connection, user_id: int) -> list[int]:
    """What "run the rules on everything" goes through."""
    return [row[0] for row in conn.execute(
        "SELECT id FROM items WHERE user_id = ? AND archived_at IS NULL ORDER BY id", (user_id,)
    )]


def apply_to_items(conn: sqlite3.Connection, user_id: int, item_ids: list[int], *, now: int) -> int:
    """Runs the rules over these items. Returns how many changed; an item deleted meanwhile is skipped."""
    rules = list_for_user(conn, user_id)
    if not rules:
        return 0
    changed = 0
    for item_id in item_ids:
        try:
            changed += apply(conn, user_id, item_id, now=now, rules=rules)
        except NotFound:
            pass
    return changed
