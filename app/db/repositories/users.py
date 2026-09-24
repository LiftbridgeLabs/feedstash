"""People who can sign in: with a FeedStash password, Google, or another OpenID Connect provider."""

import re
import sqlite3
import uuid

from app.clock import now
from app.db.models import User
from app.errors import Conflict, InvalidInput, NotFound

_SELECT = """SELECT id, sub, email, name, picture, is_admin, password_hash IS NOT NULL AS has_password, created_at,
    read_retention_days FROM users"""
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _user(row: sqlite3.Row | None) -> User | None:
    if row is None:
        return None
    return User(
        id=row["id"], sub=row["sub"], email=row["email"], name=row["name"], picture=row["picture"],
        is_admin=bool(row["is_admin"]), has_password=bool(row["has_password"]), created_at=row["created_at"],
        read_retention_days=row["read_retention_days"],
    )


def set_read_retention(conn: sqlite3.Connection, user_id: int, days: int) -> None:
    if conn.execute("UPDATE users SET read_retention_days = ? WHERE id = ?", (days, user_id)).rowcount == 0:
        raise NotFound("No such account")


def upsert(
    conn: sqlite3.Connection, *, sub: str, email: str, name: str | None, picture: str | None,
    link_by_email: bool = False,
) -> int:
    """Creates the user on first sign-in, refreshes their profile afterwards. Returns the user id.

    With `link_by_email`, a sign-in from a new subject whose email already has an account signs in to that account.
    The first user ever created is an admin.
    """
    email = normalize_email(email)
    row = conn.execute("SELECT id FROM users WHERE sub = ?", (sub,)).fetchone()
    if row is None and link_by_email:
        row = conn.execute("SELECT id FROM users WHERE email = ? ORDER BY id LIMIT 1", (email,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET email = ?, name = COALESCE(?, name), picture = COALESCE(?, picture) WHERE id = ?",
            (email, name, picture, row["id"]),
        )
        return row["id"]
    first = count(conn) == 0
    return conn.execute(
        "INSERT INTO users (sub, email, name, picture, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (sub, email, name, picture, int(first), now()),
    ).lastrowid


def create_local(conn: sqlite3.Connection, *, email: str, name: str | None, password_hash: str, is_admin: bool) -> User:
    """An account that signs in with a password."""
    email = normalize_email(email)
    if len(email) > 320 or not _EMAIL.match(email):
        raise InvalidInput("Enter a valid email address")
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise Conflict("There's already an account with that email")
    user_id = conn.execute(
        """INSERT INTO users (sub, email, name, picture, password_hash, is_admin, created_at)
           VALUES (?, ?, ?, NULL, ?, ?, ?)""",
        (f"local:{uuid.uuid4()}", email, (name or "").strip()[:100] or None, password_hash, int(is_admin), now()),
    ).lastrowid
    return get(conn, user_id)


def get(conn: sqlite3.Connection, user_id: int) -> User | None:
    return _user(conn.execute(f"{_SELECT} WHERE id = ?", (user_id,)).fetchone())


def has_sub(conn: sqlite3.Connection, sub: str) -> bool:
    """Whether an account already signs in with this provider identity."""
    return conn.execute("SELECT 1 FROM users WHERE sub = ?", (sub,)).fetchone() is not None


def find_by_email(conn: sqlite3.Connection, email: str) -> User | None:
    return _user(conn.execute(f"{_SELECT} WHERE email = ? ORDER BY id LIMIT 1", (normalize_email(email),)).fetchone())


def list_all(conn: sqlite3.Connection) -> list[User]:
    return [_user(row) for row in conn.execute(f"{_SELECT} ORDER BY email, id")]


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]


def credentials(conn: sqlite3.Connection, email: str) -> tuple[int, str] | None:
    """The id and password hash of the password account with this email."""
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ? AND password_hash IS NOT NULL ORDER BY id LIMIT 1",
        (normalize_email(email),),
    ).fetchone()
    return (row["id"], row["password_hash"]) if row else None


def get_password_hash(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["password_hash"] if row else None


def set_password(conn: sqlite3.Connection, user_id: int, password_hash: str) -> None:
    if conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)).rowcount == 0:
        raise NotFound("No such account")


def set_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool) -> None:
    if conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id)).rowcount == 0:
        raise NotFound("No such account")


def delete(conn: sqlite3.Connection, user_id: int) -> None:
    """Deletes the account and, through foreign keys, everything it follows and saved."""
    if conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount == 0:
        raise NotFound("No such account")
