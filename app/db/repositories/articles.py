import sqlite3
from collections.abc import Iterable, Sequence

from app.db.models import Article, ArticlePage, ArticleSummary, NewArticle, Scope, SortOrder
from app.errors import InvalidInput, NotFound

MAX_PAGE_SIZE = 100

_SUMMARY_COLUMNS = """a.id, a.feed_id, a.title, a.url, a.author, a.summary, a.image, a.published_at,
    a.read_at IS NOT NULL AS read, a.starred_at IS NOT NULL AS starred, f.title AS feed_title, f.site_url"""
_FROM = "FROM articles a JOIN feeds f ON f.id = a.feed_id"
_OWNED_BY = "feed_id IN (SELECT id FROM feeds WHERE user_id = ?)"


def _scope_condition(user_id: int, scope: Scope) -> tuple[str, list]:
    """SQL condition over `articles a JOIN feeds f` selecting what a sidebar entry shows."""
    if scope.kind == "all":
        return "f.user_id = ?", [user_id]
    if scope.kind == "starred":
        return "f.user_id = ? AND a.starred_at IS NOT NULL", [user_id]
    if scope.kind == "uncategorized":
        return "f.user_id = ? AND f.folder_id IS NULL", [user_id]
    if scope.id is None:
        raise InvalidInput("Missing id")
    if scope.kind == "folder":
        return "f.user_id = ? AND f.folder_id = ?", [user_id, scope.id]
    if scope.kind == "feed":
        return "f.user_id = ? AND f.id = ?", [user_id, scope.id]
    raise InvalidInput("Invalid scope")


def _summary_fields(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "feed_id": row["feed_id"], "title": row["title"], "url": row["url"],
        "author": row["author"], "summary": row["summary"], "image": row["image"],
        "published_at": row["published_at"], "read": bool(row["read"]), "starred": bool(row["starred"]),
        "feed_title": row["feed_title"], "site_url": row["site_url"],
    }


def _parse_cursor(cursor: str) -> tuple[int, int]:
    try:
        published_at, article_id = (int(part) for part in cursor.split(":"))
    except ValueError:
        raise InvalidInput("Invalid cursor") from None
    return published_at, article_id


# ------------------------------------------------------------------ reading


def page(
    conn: sqlite3.Connection,
    user_id: int,
    scope: Scope,
    *,
    unread_only: bool = True,
    order: SortOrder = "newest",
    cursor: str | None = None,
    max_id: int | None = None,
    limit: int = 40,
) -> ArticlePage:
    """One page of a scope, keyset-paginated by (published_at, id).

    `max_id` pins the list to articles that existed when the first page was loaded; the first page
    returns it so later pages (and "mark all as read") don't pick up articles fetched meanwhile.
    """
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    scope_where, scope_params = _scope_condition(user_id, scope)
    where, params = scope_where, list(scope_params)
    if unread_only and scope.kind != "starred":
        where += " AND a.read_at IS NULL"
    if max_id is not None:
        where += " AND a.id <= ?"
        params.append(max_id)
    if cursor:
        published_at, last_id = _parse_cursor(cursor)
        op = "<" if order == "newest" else ">"
        where += f" AND (a.published_at {op} ? OR (a.published_at = ? AND a.id {op} ?))"
        params += [published_at, published_at, last_id]
    direction = "DESC" if order == "newest" else "ASC"
    rows = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} {_FROM} WHERE {where} "
        f"ORDER BY a.published_at {direction}, a.id {direction} LIMIT ?",
        [*params, limit + 1],
    ).fetchall()
    if max_id is None:
        max_id = conn.execute(f"SELECT MAX(a.id) {_FROM} WHERE {scope_where}", scope_params).fetchone()[0] or 0

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = f"{rows[-1]['published_at']}:{rows[-1]['id']}" if has_more else None
    return ArticlePage([ArticleSummary(**_summary_fields(row)) for row in rows], next_cursor, max_id)


def get(conn: sqlite3.Connection, user_id: int, article_id: int) -> Article:
    row = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS}, a.content {_FROM} WHERE a.id = ? AND f.user_id = ?", (article_id, user_id)
    ).fetchone()
    if row is None:
        raise NotFound("Article not found")
    return Article(**_summary_fields(row), content=row["content"])


def count_new(conn: sqlite3.Connection, user_id: int, scope: Scope, *, since_id: int, unread_only: bool) -> int:
    """Articles that arrived in a scope after `since_id` (article ids grow in fetch order)."""
    where, params = _scope_condition(user_id, scope)
    if unread_only and scope.kind != "starred":
        where += " AND a.read_at IS NULL"
    return conn.execute(f"SELECT COUNT(*) {_FROM} WHERE {where} AND a.id > ?", [*params, since_id]).fetchone()[0]


def starred_count(conn: sqlite3.Connection, user_id: int) -> int:
    return conn.execute(
        f"SELECT COUNT(*) {_FROM} WHERE f.user_id = ? AND a.starred_at IS NOT NULL", (user_id,)
    ).fetchone()[0]


# ------------------------------------------------------------------ read & starred state


def set_read(conn: sqlite3.Connection, user_id: int, ids: Sequence[int], *, read: bool, now: int) -> int:
    if not ids:
        return 0
    owned = f"id IN ({','.join('?' * len(ids))}) AND {_OWNED_BY}"
    if read:
        sql, params = f"UPDATE articles SET read_at = ? WHERE read_at IS NULL AND {owned}", [now, *ids, user_id]
    else:
        sql, params = f"UPDATE articles SET read_at = NULL WHERE {owned}", [*ids, user_id]
    return conn.execute(sql, params).rowcount


def set_starred(conn: sqlite3.Connection, user_id: int, article_id: int, *, starred: bool, now: int) -> None:
    updated = conn.execute(
        f"UPDATE articles SET starred_at = ? WHERE id = ? AND {_OWNED_BY}",
        (now if starred else None, article_id, user_id),
    ).rowcount
    if not updated:
        raise NotFound("Article not found")


def mark_scope_read(
    conn: sqlite3.Connection, user_id: int, scope: Scope, *, batch: int,
    published_before: int | None = None, max_id: int | None = None,
) -> int:
    """Marks a scope read, stamping `batch` as read_at so the change can be undone."""
    where, params = _scope_condition(user_id, scope)
    if published_before is not None:
        where += " AND a.published_at < ?"
        params.append(published_before)
    if max_id is not None:
        where += " AND a.id <= ?"
        params.append(max_id)
    return conn.execute(
        f"UPDATE articles SET read_at = ? WHERE read_at IS NULL AND id IN (SELECT a.id {_FROM} WHERE {where})",
        [batch, *params],
    ).rowcount


def undo_mark_scope_read(conn: sqlite3.Connection, user_id: int, scope: Scope, *, batch: int) -> int:
    where, params = _scope_condition(user_id, scope)
    return conn.execute(
        f"UPDATE articles SET read_at = NULL WHERE read_at = ? AND id IN (SELECT a.id {_FROM} WHERE {where})",
        [batch, *params],
    ).rowcount


# ------------------------------------------------------------------ storing & cleanup


def insert_new(conn: sqlite3.Connection, feed_id: int, articles: Iterable[NewArticle], *, fetched_at: int) -> int:
    """Stores articles not seen before (by guid), skipping read ones the cleanup already removed. Returns how many
    were new."""
    added = 0
    for article in articles:
        added += conn.execute(
            """INSERT OR IGNORE INTO articles
                   (feed_id, guid, title, url, author, summary, content, image, published_at, fetched_at)
               SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
               WHERE NOT EXISTS (SELECT 1 FROM purged_articles WHERE feed_id = ? AND guid = ?)""",
            (feed_id, article.guid, article.title, article.url, article.author, article.summary,
             article.content, article.image, article.published_at, fetched_at, feed_id, article.guid),
        ).rowcount
    return added


def purge(conn: sqlite3.Connection, *, published_before: int, keep_per_feed: int) -> int:
    """Deletes old articles, except starred ones and the newest `keep_per_feed` of every feed."""
    return conn.execute(
        """DELETE FROM articles
           WHERE starred_at IS NULL AND published_at < ? AND id IN (
             SELECT id FROM (
               SELECT id, ROW_NUMBER() OVER (PARTITION BY feed_id ORDER BY published_at DESC, id DESC) AS rn
               FROM articles
             ) WHERE rn > ?
           )""",
        (published_before, keep_per_feed),
    ).rowcount


# Read articles (not in Read later) whose owner read them longer ago than their chosen number of days.
_READ_EXPIRED = """SELECT a.id FROM articles a JOIN feeds f ON f.id = a.feed_id JOIN users u ON u.id = f.user_id
    WHERE u.read_retention_days > 0 AND a.starred_at IS NULL AND a.read_at IS NOT NULL
      AND a.read_at < ? - u.read_retention_days * 86400"""


def purge_read(conn: sqlite3.Connection, *, now: int) -> int:
    """Deletes articles read longer ago than each owner's setting. Their guids are remembered, so the next
    refresh of a feed that still lists them doesn't bring them back as unread."""
    conn.execute(
        f"""INSERT OR IGNORE INTO purged_articles (feed_id, guid, published_at)
            SELECT feed_id, guid, published_at FROM articles WHERE id IN ({_READ_EXPIRED})""",
        (now,),
    )
    return conn.execute(f"DELETE FROM articles WHERE id IN ({_READ_EXPIRED})", (now,)).rowcount


def forget_purged(conn: sqlite3.Connection, *, published_before: int) -> int:
    """Drops remembered guids of articles old enough that refreshes skip them anyway."""
    return conn.execute("DELETE FROM purged_articles WHERE published_at < ?", (published_before,)).rowcount
