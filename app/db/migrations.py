"""Versioned schema migrations, tracked in SQLite's `PRAGMA user_version`.

To change the schema, append a new SQL script to MIGRATIONS. Never edit one that has shipped.
"""

import sqlite3

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE users (
        id          INTEGER PRIMARY KEY,
        sub         TEXT NOT NULL UNIQUE,
        email       TEXT NOT NULL,
        name        TEXT,
        picture     TEXT,
        created_at  INTEGER NOT NULL
    );
    CREATE TABLE folders (
        id          INTEGER PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        UNIQUE (user_id, name)
    );
    CREATE TABLE feeds (
        id               INTEGER PRIMARY KEY,
        user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        folder_id        INTEGER REFERENCES folders(id) ON DELETE SET NULL,
        url              TEXT NOT NULL,
        title            TEXT NOT NULL,
        site_url         TEXT,
        etag             TEXT,
        last_modified    TEXT,
        last_fetched_at  INTEGER,
        last_error       TEXT,
        created_at       INTEGER NOT NULL,
        UNIQUE (user_id, url)
    );
    CREATE INDEX idx_feeds_user ON feeds(user_id, folder_id);
    CREATE TABLE articles (
        id            INTEGER PRIMARY KEY,
        feed_id       INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
        guid          TEXT NOT NULL,
        title         TEXT NOT NULL,
        url           TEXT,
        author        TEXT,
        summary       TEXT,
        content       TEXT,
        image         TEXT,
        published_at  INTEGER NOT NULL,
        fetched_at    INTEGER NOT NULL,
        read_at       INTEGER,
        starred_at    INTEGER,
        UNIQUE (feed_id, guid)
    );
    CREATE INDEX idx_articles_feed_pub ON articles(feed_id, published_at, id);
    CREATE INDEX idx_articles_unread ON articles(feed_id) WHERE read_at IS NULL;
    CREATE INDEX idx_articles_starred ON articles(feed_id) WHERE starred_at IS NOT NULL;
    """,
    # 2: manual ordering of folders and feeds, seeded alphabetically so nothing jumps around
    """
    ALTER TABLE folders ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
    UPDATE folders SET position = (
        SELECT COUNT(*) FROM folders o
        WHERE o.user_id = folders.user_id
          AND (o.name COLLATE NOCASE < folders.name COLLATE NOCASE
               OR (o.name COLLATE NOCASE = folders.name COLLATE NOCASE AND o.id < folders.id)));
    ALTER TABLE feeds ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
    UPDATE feeds SET position = (
        SELECT COUNT(*) FROM feeds o
        WHERE o.user_id = feeds.user_id AND o.folder_id IS feeds.folder_id
          AND (o.title COLLATE NOCASE < feeds.title COLLATE NOCASE
               OR (o.title COLLATE NOCASE = feeds.title COLLATE NOCASE AND o.id < feeds.id)));
    """,
]


def latest_version() -> int:
    return len(MIGRATIONS)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def current_version(conn: sqlite3.Connection) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0 and _columns(conn, "users"):
        # Databases from before versioning existed: work out how far they already got.
        version = 2 if "position" in _columns(conn, "folders") else 1
    return version


def apply(conn: sqlite3.Connection) -> int:
    """Runs pending migrations, each in its own transaction. Returns the resulting version."""
    version = current_version(conn)
    latest = latest_version()
    if version > latest:
        raise RuntimeError(f"Database schema version {version} is newer than this app supports ({latest})")
    for number in range(version + 1, latest + 1):
        try:
            conn.executescript(f"BEGIN;\n{MIGRATIONS[number - 1]}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
    if conn.execute("PRAGMA user_version").fetchone()[0] != latest:
        conn.execute(f"PRAGMA user_version = {latest}")  # stamp databases whose version was inferred
    return latest
