import sqlite3
from collections.abc import Iterable, Sequence

from app.db.models import Article, ArticlePage, ArticleSummary, FullTextJob, NewArticle, Scope, SortOrder
from app.db.repositories import search
from app.errors import InvalidInput, NotFound

MAX_PAGE_SIZE = 100
MAX_IDS = 10_000  # what a client may ask for in one ids call; the Google Reader clients expect this ceiling
MAX_CONTENTS = 1_000  # and this one for fetching the articles behind those ids

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
    query: str | None = None,
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
    if query:
        match = search.match_query(query)
        where += f" AND {search.ARTICLE_MATCH}" if match else " AND 0"  # only punctuation: nothing to find
        if match:
            params.append(match)
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
        f"SELECT {_SUMMARY_COLUMNS}, a.content, a.full_content {_FROM} WHERE a.id = ? AND f.user_id = ?",
        (article_id, user_id),
    ).fetchone()
    if row is None:
        raise NotFound("Article not found")
    return Article(**_summary_fields(row), content=row["content"], full_content=row["full_content"])


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


def state_ids(
    conn: sqlite3.Connection, user_id: int, scope: Scope, *, state: str = "unread", since_id: int | None = None,
    limit: int = MAX_IDS,
) -> list[int]:
    """Just the ids of a scope's articles, newest first, by state ("unread", "starred" or "all").

    This is what a syncing client diffs against its own copy: ids are small enough to fetch in bulk, so the client
    can work out exactly what it's missing and what it should forget, then ask for only those.
    """
    where, params = _scope_condition(user_id, scope)
    if state == "unread":
        where += " AND a.read_at IS NULL"
    elif state == "starred":
        where += " AND a.starred_at IS NOT NULL"
    elif state != "all":
        raise InvalidInput('state must be "unread", "starred" or "all"')
    if since_id is not None:
        where += " AND a.id > ?"
        params.append(since_id)
    rows = conn.execute(
        f"SELECT a.id {_FROM} WHERE {where} ORDER BY a.published_at DESC, a.id DESC LIMIT ?",
        [*params, max(1, min(limit, MAX_IDS))],
    )
    return [row[0] for row in rows]


def stream_page(
    conn: sqlite3.Connection,
    user_id: int,
    scope: Scope,
    *,
    read: bool | None = None,
    starred: bool | None = None,
    newer_than: int | None = None,
    older_than: int | None = None,
    oldest_first: bool = False,
    limit: int = MAX_IDS,
    cursor: str | None = None,
) -> tuple[list[tuple[int, int]], str | None]:
    """(id, published_at) pairs for the Google Reader API, filtered the ways its clients ask, with a cursor to the
    next page. `read`/`starred` of None means either; `newer_than`/`older_than` are Unix seconds, inclusive."""
    where, params = _scope_condition(user_id, scope)
    for column, wanted in (("a.read_at", read), ("a.starred_at", starred)):
        if wanted is not None:
            where += f" AND {column} IS {'NOT ' if wanted else ''}NULL"
    if newer_than is not None:
        where += " AND a.published_at >= ?"
        params.append(newer_than)
    if older_than is not None:
        where += " AND a.published_at <= ?"
        params.append(older_than)
    if cursor:
        published_at, last_id = _parse_cursor(cursor)
        op = ">" if oldest_first else "<"
        where += f" AND (a.published_at {op} ? OR (a.published_at = ? AND a.id {op} ?))"
        params += [published_at, published_at, last_id]
    direction = "ASC" if oldest_first else "DESC"
    limit = max(1, min(limit, MAX_IDS))
    rows = conn.execute(
        f"SELECT a.id, a.published_at {_FROM} WHERE {where} "
        f"ORDER BY a.published_at {direction}, a.id {direction} LIMIT ?",
        [*params, limit + 1],
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = f"{rows[-1]['published_at']}:{rows[-1]['id']}" if has_more else None
    return [(row["id"], row["published_at"]) for row in rows], next_cursor


def newest_unread_by_feed(conn: sqlite3.Connection, user_id: int) -> dict[int, int]:
    """When each feed's newest unread article was published, for the Reader API's unread counts."""
    rows = conn.execute(
        f"SELECT a.feed_id, MAX(a.published_at) AS newest {_FROM} "
        "WHERE f.user_id = ? AND a.read_at IS NULL GROUP BY a.feed_id",
        (user_id,),
    )
    return {row["feed_id"]: row["newest"] for row in rows}


def max_id(conn: sqlite3.Connection, user_id: int, scope: Scope) -> int:
    """The newest article id in a scope, so a client can say "everything after this" next time."""
    where, params = _scope_condition(user_id, scope)
    return conn.execute(f"SELECT MAX(a.id) {_FROM} WHERE {where}", params).fetchone()[0] or 0


def by_ids(conn: sqlite3.Connection, user_id: int, ids: Sequence[int]) -> list[Article]:
    """The articles a client asked for by id, newest first. Ids it doesn't own are simply absent."""
    ids = list(ids)[:MAX_CONTENTS]
    if not ids:
        return []
    rows = conn.execute(
        f"""SELECT {_SUMMARY_COLUMNS}, a.content, a.full_content {_FROM}
            WHERE a.id IN ({','.join('?' * len(ids))}) AND f.user_id = ?
            ORDER BY a.published_at DESC, a.id DESC""",
        [*ids, user_id],
    ).fetchall()
    return [Article(**_summary_fields(row), content=row["content"], full_content=row["full_content"]) for row in rows]


# ------------------------------------------------------------------ full text

FULL_TEXT_RETRY_SECONDS = 600  # a fetch that never reported back (the server stopped) is tried again after this
FULL_TEXT_MAX_AGE_SECONDS = 14 * 86400  # background fetching only looks at articles that arrived recently


def claim_full_text(conn: sqlite3.Connection, *, now: int, limit: int) -> list[FullTextJob]:
    """Unread, recent articles in feeds that ask for full text and haven't been tried, marked as being worked on."""
    rows = conn.execute(
        """SELECT a.id, a.url FROM articles a JOIN feeds f ON f.id = a.feed_id
           WHERE f.full_text = 1 AND a.read_at IS NULL AND a.url IS NOT NULL AND a.fetched_at >= ?
             AND (a.full_status IS NULL OR (a.full_status = 'working' AND a.full_attempted_at < ?))
           ORDER BY a.id DESC LIMIT ?""",
        (now - FULL_TEXT_MAX_AGE_SECONDS, now - FULL_TEXT_RETRY_SECONDS, limit),
    ).fetchall()
    jobs = [FullTextJob(row["id"], row["url"]) for row in rows]
    for job in jobs:
        conn.execute(
            "UPDATE articles SET full_status = 'working', full_attempted_at = ? WHERE id = ?", (now, job.article_id)
        )
    return jobs


def full_text_job(conn: sqlite3.Connection, user_id: int, article_id: int) -> FullTextJob:
    """What fetching one article's full text on request needs; its address, or a message when it has none."""
    row = conn.execute(f"SELECT a.id, a.url {_FROM} WHERE a.id = ? AND f.user_id = ?", (article_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Article not found")
    if not row["url"]:
        raise InvalidInput("This article has no web page to fetch")
    return FullTextJob(row["id"], row["url"])


def full_text_state(conn: sqlite3.Connection, user_id: int, article_id: int) -> tuple[str | None, str | None, str | None]:
    """(status, content, error) of an article's full text."""
    row = conn.execute(
        f"SELECT a.full_status, a.full_content, a.full_error {_FROM} WHERE a.id = ? AND f.user_id = ?",
        (article_id, user_id),
    ).fetchone()
    if row is None:
        raise NotFound("Article not found")
    return row["full_status"], row["full_content"], row["full_error"]


def save_full_text(conn: sqlite3.Connection, article_id: int, html: str, *, now: int) -> None:
    conn.execute(
        """UPDATE articles SET full_status = 'ready', full_content = ?, full_error = NULL, full_attempted_at = ?
           WHERE id = ?""",
        (html, now, article_id),
    )


def save_full_text_failure(conn: sqlite3.Connection, article_id: int, error: str, *, now: int) -> None:
    """Failures aren't retried in the background (the page is usually blocked or gone); asking again tries again."""
    conn.execute(
        "UPDATE articles SET full_status = 'failed', full_error = ?, full_attempted_at = ? WHERE id = ?",
        (error, now, article_id),
    )


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


def set_starred_many(conn: sqlite3.Connection, user_id: int, ids: Sequence[int], *, starred: bool, now: int) -> int:
    """Stars or unstars a batch. Clients queue state changes while offline and send them together."""
    ids = list(ids)
    if not ids:
        return 0
    return conn.execute(
        f"UPDATE articles SET starred_at = ? WHERE id IN ({','.join('?' * len(ids))}) AND {_OWNED_BY}",
        [now if starred else None, *ids, user_id],
    ).rowcount


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


def insert_new(
    conn: sqlite3.Connection, feed_id: int, articles: Iterable[NewArticle], *, fetched_at: int,
    added_ids: list[int] | None = None,
) -> int:
    """Stores articles not seen before (by guid), skipping read ones the cleanup already removed. Returns how many
    were new."""
    added = 0
    for article in articles:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO articles
                   (feed_id, guid, title, url, author, summary, content, image, published_at, fetched_at)
               SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
               WHERE NOT EXISTS (SELECT 1 FROM purged_articles WHERE feed_id = ? AND guid = ?)""",
            (feed_id, article.guid, article.title, article.url, article.author, article.summary,
             article.content, article.image, article.published_at, fetched_at, feed_id, article.guid),
        )
        if cursor.rowcount == 1:
            search.index_article(conn, cursor.lastrowid, article.title, article.search_text or article.summary)
            added += 1
            if added_ids is not None:
                added_ids.append(cursor.lastrowid)
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
