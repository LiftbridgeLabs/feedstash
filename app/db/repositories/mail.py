"""The mailbox each account can connect, and the messages already saved from it."""

import sqlite3

from app.db.models import MailAccount
from app.errors import NotFound

_SELECT = """SELECT id, user_id, host, port, username, password, folder, allowed_senders, enabled,
    last_checked_at, last_error, saved_count FROM mail_accounts"""


def _account(row: sqlite3.Row) -> MailAccount:
    return MailAccount(
        id=row["id"], user_id=row["user_id"], host=row["host"], port=row["port"], username=row["username"],
        password=row["password"], folder=row["folder"],
        allowed_senders=[s for s in (row["allowed_senders"] or "").split(",") if s],
        enabled=bool(row["enabled"]), last_checked_at=row["last_checked_at"], last_error=row["last_error"],
        saved_count=row["saved_count"],
    )


def for_user(conn: sqlite3.Connection, user_id: int) -> MailAccount | None:
    row = conn.execute(f"{_SELECT} WHERE user_id = ?", (user_id,)).fetchone()
    return _account(row) if row else None


def get(conn: sqlite3.Connection, user_id: int) -> MailAccount:
    account = for_user(conn, user_id)
    if account is None:
        raise NotFound("No mailbox is connected")
    return account


def enabled_accounts(conn: sqlite3.Connection) -> list[MailAccount]:
    return [_account(row) for row in conn.execute(f"{_SELECT} WHERE enabled = 1 ORDER BY id")]


def save(
    conn: sqlite3.Connection, user_id: int, *, host: str, port: int, username: str, password: str, folder: str,
    allowed_senders: list[str], enabled: bool, now: int,
) -> MailAccount:
    """Connects a mailbox, or updates the one already connected. `password` is already encrypted."""
    senders = ",".join(allowed_senders)
    conn.execute(
        """INSERT INTO mail_accounts (user_id, host, port, username, password, folder, allowed_senders, enabled,
               created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET host = excluded.host, port = excluded.port,
               username = excluded.username, password = excluded.password, folder = excluded.folder,
               allowed_senders = excluded.allowed_senders, enabled = excluded.enabled,
               last_error = NULL, updated_at = excluded.updated_at""",
        (user_id, host, port, username, password, folder, senders, int(enabled), now, now),
    )
    return get(conn, user_id)


def record_check(conn: sqlite3.Connection, account_id: int, *, now: int, error: str | None, saved: int = 0) -> None:
    conn.execute(
        """UPDATE mail_accounts SET last_checked_at = ?, last_error = ?, saved_count = saved_count + ?
           WHERE id = ?""",
        (now, error, saved, account_id),
    )


def delete(conn: sqlite3.Connection, user_id: int) -> None:
    get(conn, user_id)
    conn.execute("DELETE FROM mail_accounts WHERE user_id = ?", (user_id,))


def already_saved(conn: sqlite3.Connection, account_id: int, message_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM mail_messages WHERE account_id = ? AND message_id = ?", (account_id, message_id)
    ).fetchone() is not None


def remember(conn: sqlite3.Connection, account_id: int, message_id: str, *, now: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO mail_messages (account_id, message_id, seen_at) VALUES (?, ?, ?)",
        (account_id, message_id, now),
    )


def forget_seen(conn: sqlite3.Connection, *, seen_before: int) -> int:
    """Drops remembered Message-IDs old enough that a mailbox won't hand the message over again."""
    return conn.execute("DELETE FROM mail_messages WHERE seen_at < ?", (seen_before,)).rowcount
