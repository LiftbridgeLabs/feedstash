"""Password-reset links ("Forgot password?"). Only a SHA-256 hash of each link's token is stored, like API tokens."""

import secrets
import sqlite3

from app.db.repositories.tokens import hash_token
from app.errors import NotFound

TOKEN_BYTES = 32
LIFETIME_SECONDS = 60 * 60
GONE = "This reset link has been used or has expired. Ask for a new one from the sign-in page."


def create(conn: sqlite3.Connection, user_id: int, *, now: int) -> str:
    """A new link for the account, replacing any earlier unused one. Returns its token (not retrievable later)."""
    conn.execute("DELETE FROM password_resets WHERE user_id = ? AND used_at IS NULL", (user_id,))
    token = secrets.token_urlsafe(TOKEN_BYTES)
    conn.execute(
        "INSERT INTO password_resets (user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, hash_token(token), now, now + LIFETIME_SECONDS),
    )
    return token


def usable(conn: sqlite3.Connection, token: str, *, now: int) -> int:
    """The id of the reset behind a link's token, if it can still be used."""
    row = conn.execute(
        "SELECT id FROM password_resets WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
        (hash_token(token or ""), now),
    ).fetchone()
    if row is None:
        raise NotFound(GONE)
    return row["id"]


def use(conn: sqlite3.Connection, reset_id: int, *, now: int) -> int:
    """Uses a reset up and returns its account. Two tabs using one link at once: only the first gets through."""
    row = conn.execute(
        "UPDATE password_resets SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ? RETURNING user_id",
        (now, reset_id, now),
    ).fetchone()
    if row is None:
        raise NotFound(GONE)
    return row["user_id"]


def purge(conn: sqlite3.Connection, *, now: int) -> None:
    """Forgets links that can no longer be used."""
    conn.execute("DELETE FROM password_resets WHERE expires_at <= ? OR used_at IS NOT NULL", (now,))
