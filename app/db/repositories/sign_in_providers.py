"""Sign-in providers added in Settings → Sign-in. Secrets arrive and leave encrypted; this layer never sees them
in the clear."""

import sqlite3

from app.db.models import SignInProvider
from app.errors import NotFound

_COLUMNS = "id, kind, name, issuer, client_id, client_secret, scopes, enabled, position, updated_at"


def _provider(row: sqlite3.Row) -> SignInProvider:
    return SignInProvider(**{**dict(row), "enabled": bool(row["enabled"])})


def list_all(conn: sqlite3.Connection) -> list[SignInProvider]:
    return [_provider(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM sign_in_providers ORDER BY position, id")]


def get(conn: sqlite3.Connection, provider_id: int) -> SignInProvider:
    row = conn.execute(f"SELECT {_COLUMNS} FROM sign_in_providers WHERE id = ?", (provider_id,)).fetchone()
    if row is None:
        raise NotFound("That sign-in isn't set up here")
    return _provider(row)


def create(
    conn: sqlite3.Connection, *, kind: str, name: str, issuer: str, client_id: str, client_secret: str, scopes: str,
    now: int,
) -> SignInProvider:
    position = conn.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM sign_in_providers").fetchone()[0]
    cursor = conn.execute(
        """INSERT INTO sign_in_providers
               (kind, name, issuer, client_id, client_secret, scopes, enabled, position, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (kind, name, issuer, client_id, client_secret, scopes, position, now, now),
    )
    return get(conn, cursor.lastrowid)


def update(conn: sqlite3.Connection, provider_id: int, *, now: int, **fields) -> SignInProvider:
    """Changes the given columns (name, issuer, client_id, client_secret, scopes, enabled)."""
    get(conn, provider_id)
    allowed = {"name", "issuer", "client_id", "client_secret", "scopes", "enabled"}
    changes = {key: value for key, value in fields.items() if key in allowed}
    if changes:
        assignments = ", ".join(f"{key} = ?" for key in changes)
        conn.execute(
            f"UPDATE sign_in_providers SET {assignments}, updated_at = ? WHERE id = ?",
            [*changes.values(), now, provider_id],
        )
    return get(conn, provider_id)


def delete(conn: sqlite3.Connection, provider_id: int) -> None:
    get(conn, provider_id)
    conn.execute("DELETE FROM sign_in_providers WHERE id = ?", (provider_id,))
