"""Muted words: catching up the unread articles a newly muted word matches."""

import sqlite3

from app.db.models import MutedWord
from app.db.repositories import articles as articles_repo
from app.db.repositories import muted_words
from app.feeds.mute import Matcher


def mark_unread_read(conn: sqlite3.Connection, user_id: int, word: MutedWord, *, batch: int) -> int:
    """Marks read the unread articles the word matches where it applies, stamped with `batch` so the mark-read undo
    can bring them back. Returns how many."""
    matcher = Matcher.of([word])
    ids = [row["id"] for row in muted_words.unread_articles(conn, user_id, word) if matcher.mutes(row["title"], row["text"])]
    marked = 0
    for start in range(0, len(ids), 500):
        marked += articles_repo.set_read(conn, user_id, ids[start:start + 500], read=True, now=batch)
    return marked
