"""Server-wide settings changed in the app (not per account), stored as text by key."""

import sqlite3


def get_all(conn: sqlite3.Connection, prefix: str = "") -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM app_settings WHERE key LIKE ? || '%'", (prefix,))
    return {row["key"]: row["value"] for row in rows}


def count_up(conn: sqlite3.Connection, key: str, *, limit: int) -> bool:
    """Adds one to a counter kept under `key`, unless it has reached `limit`. Returns whether it was counted."""
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    count = int(row["value"]) if row and row["value"].isdigit() else 0
    if count >= limit:
        return False
    set_many(conn, {key: str(count + 1)})
    return True


def forget_others(conn: sqlite3.Connection, prefix: str, keep: str) -> None:
    """Deletes every key under `prefix` but `keep` (yesterday's counters)."""
    conn.execute("DELETE FROM app_settings WHERE key LIKE ? || '%' AND key != ?", (prefix, keep))


def set_many(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        list(values.items()),
    )
