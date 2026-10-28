"""Invite links. Only a SHA-256 hash of each link's token is stored; the token is shown once, when it's made."""

import secrets
import sqlite3

from app.db.models import Invite
from app.db.repositories.tokens import hash_token
from app.db.repositories.users import valid_email
from app.errors import InvalidInput, NotFound

TOKEN_BYTES = 32
EXPIRY_DAYS = (1, 7, 30)
GONE = "This invite link has been used, has expired or was canceled. Ask whoever sent it for a new one."
_SELECT = """SELECT i.id, i.email, COALESCE(u.name, u.email) AS created_by, i.created_at, i.expires_at
    FROM invites i LEFT JOIN users u ON u.id = i.created_by"""


def create(
    conn: sqlite3.Connection, created_by: int, *, email: str | None, days: int, now: int
) -> tuple[Invite, str]:
    """Makes an invite. Returns it and its token (not retrievable later)."""
    if days not in EXPIRY_DAYS:
        raise InvalidInput(f"An invite lasts {', '.join(map(str, EXPIRY_DAYS))} days")
    email = valid_email(email) if email and email.strip() else None
    token = secrets.token_urlsafe(TOKEN_BYTES)
    invite_id = conn.execute(
        "INSERT INTO invites (token_hash, email, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (hash_token(token), email, created_by, now, now + days * 86400),
    ).lastrowid
    return get(conn, invite_id), token


def get(conn: sqlite3.Connection, invite_id: int) -> Invite:
    row = conn.execute(f"{_SELECT} WHERE i.id = ?", (invite_id,)).fetchone()
    if row is None:
        raise NotFound("Invite not found")
    return Invite(**dict(row))


def pending(conn: sqlite3.Connection, *, now: int) -> list[Invite]:
    """Invites not yet used and not expired, newest first."""
    rows = conn.execute(
        f"{_SELECT} WHERE i.used_at IS NULL AND i.expires_at > ? ORDER BY i.created_at DESC, i.id DESC", (now,)
    )
    return [Invite(**dict(row)) for row in rows]


def usable(conn: sqlite3.Connection, token: str, *, now: int) -> Invite:
    """The invite behind a link's token, if it can still be used."""
    row = conn.execute(
        f"{_SELECT} WHERE i.token_hash = ? AND i.used_at IS NULL AND i.expires_at > ?", (hash_token(token or ""), now)
    ).fetchone()
    if row is None:
        raise NotFound(GONE)
    return Invite(**dict(row))


def use(conn: sqlite3.Connection, invite_id: int, user_id: int, *, now: int) -> None:
    """Marks an invite used. Two people using one link at once: only the first gets through."""
    used = conn.execute(
        "UPDATE invites SET used_at = ?, used_by = ? WHERE id = ? AND used_at IS NULL", (now, user_id, invite_id)
    ).rowcount
    if not used:
        raise NotFound(GONE)


def delete(conn: sqlite3.Connection, invite_id: int) -> None:
    if not conn.execute("DELETE FROM invites WHERE id = ?", (invite_id,)).rowcount:
        raise NotFound("Invite not found")
