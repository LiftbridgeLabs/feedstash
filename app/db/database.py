import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app import clock
from app.db import migrations
from app.db.repositories import pages, search


class Database:
    """Opens SQLite connections. Each unit of work gets its own connection via `transaction()`."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commits when the block succeeds, rolls back when it raises."""
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """Creates the database file if needed and brings the schema up to date."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            migrations.apply(conn)
            with conn:
                # Search and saved pages arrived after data did: index and queue anything that predates them.
                search.backfill(conn)
                pages.queue_missing(conn, now=clock.now())
        finally:
            conn.close()
