"""The schema shipped by the first release: no ordering columns and no schema version."""

import sqlite3
import time
from pathlib import Path

LEGACY_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY, sub TEXT NOT NULL UNIQUE, email TEXT NOT NULL, name TEXT, picture TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE folders (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL, UNIQUE (user_id, name)
);
CREATE TABLE feeds (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL, url TEXT NOT NULL, title TEXT NOT NULL,
    site_url TEXT, etag TEXT, last_modified TEXT, last_fetched_at INTEGER, last_error TEXT,
    created_at INTEGER NOT NULL, UNIQUE (user_id, url)
);
CREATE INDEX idx_feeds_user ON feeds(user_id, folder_id);
CREATE TABLE articles (
    id INTEGER PRIMARY KEY, feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid TEXT NOT NULL, title TEXT NOT NULL, url TEXT, author TEXT, summary TEXT, content TEXT, image TEXT,
    published_at INTEGER NOT NULL, fetched_at INTEGER NOT NULL, read_at INTEGER, starred_at INTEGER,
    UNIQUE (feed_id, guid)
);
CREATE INDEX idx_articles_feed_pub ON articles(feed_id, published_at, id);
CREATE INDEX idx_articles_unread ON articles(feed_id) WHERE read_at IS NULL;
CREATE INDEX idx_articles_starred ON articles(feed_id) WHERE starred_at IS NOT NULL;
"""


def make_legacy_db(path: Path) -> None:
    """A first-release database owned by the DEV_LOGIN user, with unsorted folders and feeds."""
    now = int(time.time())
    with sqlite3.connect(path) as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO users (id, sub, email, name, created_at) VALUES (1, 'dev-login', 'dev@localhost', 'Local user', ?)",
            (now,),
        )
        for name in ("beta", "Alpha", "gamma"):
            conn.execute("INSERT INTO folders (user_id, name) VALUES (1, ?)", (name,))
        beta = conn.execute("SELECT id FROM folders WHERE name = 'beta'").fetchone()[0]
        for folder_id, title in [(beta, "zulu"), (beta, "Echo"), (beta, "alpha"), (None, "b"), (None, "a")]:
            # Marked as just fetched so the background refresher leaves these unreachable URLs alone.
            conn.execute(
                "INSERT INTO feeds (user_id, folder_id, url, title, last_fetched_at, created_at) VALUES (1, ?, ?, ?, ?, ?)",
                (folder_id, f"http://127.0.0.1:9/{title}.xml", title, now, now),
            )
        conn.execute(
            "INSERT INTO articles (feed_id, guid, title, published_at, fetched_at) VALUES (1, 'g1', 'Kept', ?, ?)",
            (now, now),
        )
