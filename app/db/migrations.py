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
    # 3: the stash (captured links, snippets, screenshots, emails) and API tokens for its clients
    """
    CREATE TABLE items (
        id           INTEGER PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type         TEXT NOT NULL CHECK (type IN ('link', 'snippet', 'screenshot', 'email')),
        title        TEXT,
        content      TEXT,
        url          TEXT,
        image_name   TEXT,
        source       TEXT NOT NULL DEFAULT 'web',
        reviewed_at  INTEGER,
        archived_at  INTEGER,
        created_at   INTEGER NOT NULL,
        updated_at   INTEGER NOT NULL
    );
    CREATE INDEX idx_items_user ON items(user_id, archived_at, created_at);
    CREATE TABLE tags (
        id       INTEGER PRIMARY KEY,
        user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name     TEXT NOT NULL,
        UNIQUE (user_id, name)
    );
    CREATE TABLE item_tags (
        item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (item_id, tag_id)
    );
    CREATE INDEX idx_item_tags_tag ON item_tags(tag_id);
    CREATE TABLE api_tokens (
        id            INTEGER PRIMARY KEY,
        user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash    TEXT NOT NULL UNIQUE,
        hint          TEXT NOT NULL,
        client_name   TEXT NOT NULL,
        created_at    INTEGER NOT NULL,
        last_used_at  INTEGER
    );
    """,
    # 4: several links per stash item; items.url mirrors the first one
    """
    CREATE TABLE item_links (
        id        INTEGER PRIMARY KEY,
        item_id   INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        url       TEXT NOT NULL,
        label     TEXT,
        position  INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_item_links_item ON item_links(item_id, position);
    INSERT INTO item_links (item_id, url, position) SELECT id, url, 0 FROM items WHERE url IS NOT NULL;
    """,
    # 5: password sign-in and admins; sign-in subjects say which provider they came from
    """
    ALTER TABLE users ADD COLUMN password_hash TEXT;
    ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;
    UPDATE users SET sub = 'google:' || sub WHERE sub <> 'dev-login' AND instr(sub, ':') = 0;
    UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users);
    CREATE INDEX idx_users_email ON users(email);
    """,
    # 6: each account chooses how long read articles are kept; guids of deleted read articles are remembered so a
    #    refresh doesn't bring them back as unread
    """
    ALTER TABLE users ADD COLUMN read_retention_days INTEGER NOT NULL DEFAULT 30;
    CREATE TABLE purged_articles (
        feed_id       INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
        guid          TEXT NOT NULL,
        published_at  INTEGER NOT NULL,
        PRIMARY KEY (feed_id, guid)
    ) WITHOUT ROWID;
    CREATE INDEX idx_purged_articles_published ON purged_articles(published_at);
    """,
    # 7: the web page behind each saved item (link preview and readable copy), and full-text search over the
    #    stash and feed articles. Existing rows are indexed and queued at startup (see Database.initialize).
    """
    CREATE TABLE item_pages (
        item_id      INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
        url          TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        attempts     INTEGER NOT NULL DEFAULT 0,
        not_before   INTEGER NOT NULL DEFAULT 0,
        error        TEXT,
        fetched_at   INTEGER,
        title        TEXT,
        description  TEXT,
        image_url    TEXT,
        site_name    TEXT,
        text         TEXT,
        html         TEXT
    );
    CREATE INDEX idx_item_pages_queue ON item_pages(status, not_before);
    CREATE VIRTUAL TABLE items_fts USING fts5(title, body, tokenize = 'porter unicode61 remove_diacritics 2');
    CREATE VIRTUAL TABLE articles_fts USING fts5(title, body, tokenize = 'porter unicode61 remove_diacritics 2');
    CREATE TRIGGER items_fts_delete AFTER DELETE ON items BEGIN
        DELETE FROM items_fts WHERE rowid = old.id;
    END;
    CREATE TRIGGER articles_fts_delete AFTER DELETE ON articles BEGIN
        DELETE FROM articles_fts WHERE rowid = old.id;
    END;
    """,
    # 8: organizing the stash: folders (an item is in at most one), smart lists (saved searches), rules applied to
    #    new items, the feed an item came from, and feeds whose new articles go straight to the stash
    """
    CREATE TABLE stash_folders (
        id        INTEGER PRIMARY KEY,
        user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name      TEXT NOT NULL,
        position  INTEGER NOT NULL DEFAULT 0,
        UNIQUE (user_id, name)
    );
    ALTER TABLE items ADD COLUMN folder_id INTEGER REFERENCES stash_folders(id) ON DELETE SET NULL;
    ALTER TABLE items ADD COLUMN feed_id INTEGER REFERENCES feeds(id) ON DELETE SET NULL;
    CREATE INDEX idx_items_folder ON items(folder_id);
    CREATE INDEX idx_items_feed ON items(feed_id);
    CREATE TABLE smart_lists (
        id         INTEGER PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name       TEXT NOT NULL,
        position   INTEGER NOT NULL DEFAULT 0,
        query      TEXT,
        type       TEXT,
        tag        TEXT,
        folder_id  INTEGER REFERENCES stash_folders(id) ON DELETE CASCADE,
        UNIQUE (user_id, name)
    );
    CREATE TABLE stash_rules (
        id             INTEGER PRIMARY KEY,
        user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        position       INTEGER NOT NULL DEFAULT 0,
        field          TEXT NOT NULL,
        value          TEXT NOT NULL,
        add_tag        TEXT,
        folder_id      INTEGER REFERENCES stash_folders(id) ON DELETE SET NULL,
        mark_reviewed  INTEGER NOT NULL DEFAULT 0,
        archive        INTEGER NOT NULL DEFAULT 0,
        created_at     INTEGER NOT NULL
    );
    ALTER TABLE feeds ADD COLUMN auto_stash INTEGER NOT NULL DEFAULT 0;
    """,
    # 9: a mailbox FeedStash checks for you, so forwarding an email saves it. The password is encrypted with the
    #    server's secret key; message ids are remembered so nothing is saved twice.
    """
    CREATE TABLE mail_accounts (
        id               INTEGER PRIMARY KEY,
        user_id          INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        host             TEXT NOT NULL,
        port             INTEGER NOT NULL DEFAULT 993,
        username         TEXT NOT NULL,
        password         TEXT NOT NULL,
        folder           TEXT NOT NULL DEFAULT 'INBOX',
        allowed_senders  TEXT NOT NULL DEFAULT '',
        enabled          INTEGER NOT NULL DEFAULT 1,
        last_checked_at  INTEGER,
        last_error       TEXT,
        saved_count      INTEGER NOT NULL DEFAULT 0,
        created_at       INTEGER NOT NULL,
        updated_at       INTEGER NOT NULL
    );
    CREATE TABLE mail_messages (
        account_id  INTEGER NOT NULL REFERENCES mail_accounts(id) ON DELETE CASCADE,
        message_id  TEXT NOT NULL,
        seen_at     INTEGER NOT NULL,
        PRIMARY KEY (account_id, message_id)
    );
    """,
    # 10: full text for feed articles. A feed can ask for every new article's page to be fetched; any article can
    # be fetched on request. full_status: NULL (not tried), working, ready, failed.
    """
    ALTER TABLE feeds ADD COLUMN full_text INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE articles ADD COLUMN full_content TEXT;
    ALTER TABLE articles ADD COLUMN full_status TEXT;
    ALTER TABLE articles ADD COLUMN full_error TEXT;
    ALTER TABLE articles ADD COLUMN full_attempted_at INTEGER;
    CREATE INDEX idx_articles_full_text_due ON articles(feed_id) WHERE full_status IS NULL AND read_at IS NULL;
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
