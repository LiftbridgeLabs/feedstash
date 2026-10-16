"""Server-wide settings changed in the app (not per account), stored as text by key."""

import sqlite3


def get_all(conn: sqlite3.Connection, prefix: str = "") -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM app_settings WHERE key LIKE ? || '%'", (prefix,))
    return {row["key"]: row["value"] for row in rows}


def set_many(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        list(values.items()),
    )
