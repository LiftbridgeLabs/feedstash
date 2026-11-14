"""Passkeys: each account's WebAuthn credentials (public keys only; the private key never leaves the device)."""

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Passkey:
    id: int
    user_id: int
    credential_id: str  # base64url, as the browser reports it
    public_key: bytes
    sign_count: int
    transports: list[str]
    user_handle: str
    rp_id: str
    name: str
    created_at: int
    last_used_at: int | None


_SELECT = ("SELECT id, user_id, credential_id, public_key, sign_count, transports, user_handle, rp_id, name, "
           "created_at, last_used_at FROM passkeys")


def _passkey(row) -> Passkey | None:
    if row is None:
        return None
    try:
        transports = [str(t) for t in json.loads(row["transports"] or "[]")]
    except (ValueError, TypeError):
        transports = []
    return Passkey(row["id"], row["user_id"], row["credential_id"], bytes(row["public_key"]), row["sign_count"],
                   transports, row["user_handle"], row["rp_id"], row["name"], row["created_at"], row["last_used_at"])


def for_user(conn: sqlite3.Connection, user_id: int) -> list[Passkey]:
    return [_passkey(row) for row in conn.execute(f"{_SELECT} WHERE user_id = ? ORDER BY created_at, id", (user_id,))]


def by_credential(conn: sqlite3.Connection, credential_id: str) -> Passkey | None:
    return _passkey(conn.execute(f"{_SELECT} WHERE credential_id = ?", (credential_id,)).fetchone())


def any_for(conn: sqlite3.Connection, rp_id: str) -> bool:
    """Whether anyone has a passkey for this address (the sign-in page only offers passkeys then)."""
    return conn.execute("SELECT 1 FROM passkeys WHERE rp_id = ? LIMIT 1", (rp_id,)).fetchone() is not None


def user_handle(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT user_handle FROM passkeys WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
    return row[0] if row else None


def add(
    conn: sqlite3.Connection, user_id: int, *, credential_id: str, public_key: bytes, sign_count: int,
    transports: list[str], user_handle: str, rp_id: str, name: str, now: int,
) -> Passkey:
    cursor = conn.execute(
        "INSERT INTO passkeys (user_id, credential_id, public_key, sign_count, transports, user_handle, rp_id, name, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, credential_id, public_key, sign_count, json.dumps(transports), user_handle, rp_id, name, now),
    )
    return _passkey(conn.execute(f"{_SELECT} WHERE id = ?", (cursor.lastrowid,)).fetchone())


def used(conn: sqlite3.Connection, passkey_id: int, *, sign_count: int, now: int) -> None:
    """The count only ever goes up: of two sign-ins finishing at once, the later-numbered one is the one kept."""
    conn.execute("UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ? AND sign_count <= ?",
                 (sign_count, now, passkey_id, sign_count))


def rename(conn: sqlite3.Connection, user_id: int, passkey_id: int, name: str) -> bool:
    return conn.execute("UPDATE passkeys SET name = ? WHERE id = ? AND user_id = ?",
                        (name, passkey_id, user_id)).rowcount == 1


def delete(conn: sqlite3.Connection, user_id: int, passkey_id: int) -> bool:
    return conn.execute("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (passkey_id, user_id)).rowcount == 1


def delete_all(conn: sqlite3.Connection, user_id: int) -> int:
    return conn.execute("DELETE FROM passkeys WHERE user_id = ?", (user_id,)).rowcount
