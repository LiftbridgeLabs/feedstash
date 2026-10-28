"""Muted words: stored per account, matched by `app.feeds.mute`."""

import sqlite3

from app.db.models import MutedWord
from app.errors import InvalidInput, NotFound

MAX_WORDS = 500
_SELECT = "SELECT id, phrase, title_only, folder_id, feed_id FROM muted_words"


def _word(row: sqlite3.Row) -> MutedWord:
    return MutedWord(
        id=row["id"], phrase=row["phrase"], title_only=bool(row["title_only"]), folder_id=row["folder_id"],
        feed_id=row["feed_id"],
    )


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[MutedWord]:
    return [_word(row) for row in conn.execute(
        f"{_SELECT} WHERE user_id = ? ORDER BY phrase COLLATE NOCASE, id", (user_id,)
    )]


def get(conn: sqlite3.Connection, user_id: int, word_id: int) -> MutedWord:
    row = conn.execute(f"{_SELECT} WHERE id = ? AND user_id = ?", (word_id, user_id)).fetchone()
    if row is None:
        raise NotFound("Muted word not found")
    return _word(row)


def for_feed(conn: sqlite3.Connection, feed_id: int) -> tuple[list[MutedWord], int | None]:
    """The feed owner's muted words, and the feed's folder, for deciding which of its new articles are muted."""
    row = conn.execute("SELECT user_id, folder_id FROM feeds WHERE id = ?", (feed_id,)).fetchone()
    if row is None:
        return [], None
    return list_for_user(conn, row["user_id"]), row["folder_id"]


def create(
    conn: sqlite3.Connection, user_id: int, *, phrase: str, title_only: bool = True, folder_id: int | None = None,
    feed_id: int | None = None, now: int,
) -> MutedWord:
    """Mutes a word or phrase (already cleaned). Muting the same phrase in the same place again returns the one
    already there, with `title_only` updated."""
    if not phrase:
        raise InvalidInput("Type a word or phrase to mute")
    if folder_id is not None and feed_id is not None:
        raise InvalidInput("Mute a word in one folder or one feed, not both")
    if folder_id is not None and not conn.execute(
        "SELECT 1 FROM folders WHERE id = ? AND user_id = ?", (folder_id, user_id)
    ).fetchone():
        raise NotFound("Folder not found")
    if feed_id is not None and not conn.execute(
        "SELECT 1 FROM feeds WHERE id = ? AND user_id = ?", (feed_id, user_id)
    ).fetchone():
        raise NotFound("Feed not found")
    existing = conn.execute(
        """SELECT id FROM muted_words WHERE user_id = ? AND phrase = ? COLLATE NOCASE
               AND folder_id IS ? AND feed_id IS ?""",
        (user_id, phrase, folder_id, feed_id),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE muted_words SET title_only = ? WHERE id = ? AND user_id = ?",
            (int(title_only), existing["id"], user_id),
        )
        return get(conn, user_id, existing["id"])
    count = conn.execute("SELECT COUNT(*) FROM muted_words WHERE user_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_WORDS:
        raise InvalidInput(f"You can mute up to {MAX_WORDS} words. Remove some you no longer need first.")
    word_id = conn.execute(
        """INSERT INTO muted_words (user_id, phrase, title_only, folder_id, feed_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, phrase, int(title_only), folder_id, feed_id, now),
    ).lastrowid
    return get(conn, user_id, word_id)


def delete(conn: sqlite3.Connection, user_id: int, word_id: int) -> None:
    get(conn, user_id, word_id)
    conn.execute("DELETE FROM muted_words WHERE id = ? AND user_id = ?", (word_id, user_id))


def unread_articles(conn: sqlite3.Connection, user_id: int, word: MutedWord) -> list[sqlite3.Row]:
    """Unread articles where a muted word applies: id, title and the text the search index holds."""
    where, params = "f.user_id = ? AND a.read_at IS NULL", [user_id]
    if word.feed_id is not None:
        where += " AND f.id = ?"
        params.append(word.feed_id)
    elif word.folder_id is not None:
        where += " AND f.folder_id = ?"
        params.append(word.folder_id)
    return conn.execute(
        f"""SELECT a.id, a.title, s.body AS text
            FROM articles a JOIN feeds f ON f.id = a.feed_id LEFT JOIN articles_fts s ON s.rowid = a.id
            WHERE {where}""",
        params,
    ).fetchall()
