"""API tokens for non-browser clients (browser extension, email worker, phone apps).

Only a SHA-256 hash of each token is stored; the value is shown once, when it's created.
"""

import hashlib
import secrets
import sqlite3

from app.db.models import ApiToken, TokenMatch
from app.db.repositories._common import clean_name
from app.errors import NotFound

TOKEN_BYTES = 24
TOUCH_INTERVAL_SECONDS = 60  # don't rewrite last_used_at on every single request


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(conn: sqlite3.Connection, user_id: int, client_name: str, *, now: int) -> tuple[ApiToken, str]:
    """Mints a new token. Returns the stored record and the token value (not retrievable later)."""
    name = clean_name(client_name, "Client name")
    secret = secrets.token_urlsafe(TOKEN_BYTES)
    token_id = conn.execute(
        "INSERT INTO api_tokens (user_id, token_hash, hint, client_name, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, hash_token(secret), secret[-4:], name, now),
    ).lastrowid
    return ApiToken(id=token_id, client_name=name, hint=secret[-4:], created_at=now, last_used_at=None), secret


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[ApiToken]:
    rows = conn.execute(
        """SELECT id, client_name, hint, created_at, last_used_at FROM api_tokens
           WHERE user_id = ? ORDER BY created_at DESC, id DESC""",
        (user_id,),
    )
    return [ApiToken(**dict(row)) for row in rows]


def delete(conn: sqlite3.Connection, user_id: int, token_id: int) -> None:
    if not conn.execute("DELETE FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user_id)).rowcount:
        raise NotFound("Not found")


def authenticate(conn: sqlite3.Connection, secret: str, *, now: int) -> TokenMatch | None:
    row = conn.execute(
        "SELECT id, user_id, client_name FROM api_tokens WHERE token_hash = ?", (hash_token(secret),)
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE api_tokens SET last_used_at = ? WHERE id = ? AND (last_used_at IS NULL OR last_used_at <= ?)",
        (now, row["id"], now - TOUCH_INTERVAL_SECONDS),
    )
    return TokenMatch(token_id=row["id"], user_id=row["user_id"], client_name=row["client_name"])
