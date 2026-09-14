import sqlite3

from app.clock import now
from app.db.models import User


def upsert(conn: sqlite3.Connection, *, sub: str, email: str, name: str | None, picture: str | None) -> int:
    """Creates the user on first sign-in, refreshes their profile afterwards. Returns the user id."""
    row = conn.execute("SELECT id FROM users WHERE sub = ?", (sub,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET email = ?, name = ?, picture = ? WHERE id = ?", (email, name, picture, row["id"])
        )
        return row["id"]
    return conn.execute(
        "INSERT INTO users (sub, email, name, picture, created_at) VALUES (?, ?, ?, ?, ?)",
        (sub, email, name, picture, now()),
    ).lastrowid


def get(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT id, sub, email, name, picture FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(**dict(row)) if row else None
