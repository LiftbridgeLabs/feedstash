"""Two-step sign-in: each account's authenticator secret (encrypted by the caller) and its recovery codes."""

import sqlite3
from dataclasses import dataclass

from app.db.repositories.tokens import hash_token


@dataclass(frozen=True, slots=True)
class TwoStep:
    user_id: int
    secret: str  # as stored: encrypted with the server's SecretBox
    enabled: bool
    last_step: int


def get(conn: sqlite3.Connection, user_id: int) -> TwoStep | None:
    row = conn.execute("SELECT user_id, secret, enabled_at, last_step FROM two_step WHERE user_id = ?",
                       (user_id,)).fetchone()
    return TwoStep(row["user_id"], row["secret"], row["enabled_at"] is not None, row["last_step"]) if row else None


def enabled(conn: sqlite3.Connection, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM two_step WHERE user_id = ? AND enabled_at IS NOT NULL",
                        (user_id,)).fetchone() is not None


def enabled_ids(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT user_id FROM two_step WHERE enabled_at IS NOT NULL")}


def start(conn: sqlite3.Connection, user_id: int, secret: str, *, now: int) -> None:
    """A new secret waiting for its first code; replaces one that was never confirmed (never an enabled one)."""
    conn.execute("DELETE FROM two_step WHERE user_id = ? AND enabled_at IS NULL", (user_id,))
    conn.execute("INSERT INTO two_step (user_id, secret, created_at) VALUES (?, ?, ?)", (user_id, secret, now))


def enable(conn: sqlite3.Connection, user_id: int, *, step: int, now: int) -> None:
    conn.execute("UPDATE two_step SET enabled_at = ?, last_step = ? WHERE user_id = ?", (now, step, user_id))


def use_step(conn: sqlite3.Connection, user_id: int, step: int) -> bool:
    """Records a code's step as used. False if that step (or a later one) was used already: a replayed code."""
    return conn.execute("UPDATE two_step SET last_step = ? WHERE user_id = ? AND last_step < ?",
                        (step, user_id, step)).rowcount == 1


def delete(conn: sqlite3.Connection, user_id: int) -> bool:
    conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    return conn.execute("DELETE FROM two_step WHERE user_id = ?", (user_id,)).rowcount > 0


def replace_recovery_codes(conn: sqlite3.Connection, user_id: int, codes: list[str]) -> None:
    conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    conn.executemany("INSERT INTO recovery_codes (user_id, code_hash) VALUES (?, ?)",
                     [(user_id, hash_token(code)) for code in codes])


def use_recovery_code(conn: sqlite3.Connection, user_id: int, code: str, *, now: int) -> bool:
    return conn.execute(
        "UPDATE recovery_codes SET used_at = ? WHERE user_id = ? AND code_hash = ? AND used_at IS NULL",
        (now, user_id, hash_token(code)),
    ).rowcount == 1


def recovery_codes_left(conn: sqlite3.Connection, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM recovery_codes WHERE user_id = ? AND used_at IS NULL",
                        (user_id,)).fetchone()[0]
