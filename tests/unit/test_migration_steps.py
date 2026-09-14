import sqlite3

import pytest

from app.db import migrations
from support.legacy import LEGACY_SCHEMA


def memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def columns(conn, table) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_a_fresh_database_gets_the_latest_schema():
    conn = memory_db()
    assert migrations.apply(conn) == migrations.latest_version() == version(conn)
    assert "position" in columns(conn, "folders")
    assert "position" in columns(conn, "feeds")


def test_applying_twice_changes_nothing():
    conn = memory_db()
    migrations.apply(conn)
    migrations.apply(conn)
    assert version(conn) == migrations.latest_version()


def test_a_first_release_database_is_upgraded_with_alphabetical_positions():
    conn = memory_db()
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO users (id, sub, email, created_at) VALUES (1, 's', 'e@example.com', 0)")
    conn.executemany("INSERT INTO folders (user_id, name) VALUES (1, ?)", [("beta",), ("Alpha",)])
    conn.commit()

    migrations.apply(conn)
    assert [row["name"] for row in conn.execute("SELECT name FROM folders ORDER BY position")] == ["Alpha", "beta"]
    assert version(conn) == migrations.latest_version()


def test_an_unversioned_database_that_already_has_ordering_is_only_stamped():
    conn = memory_db()
    conn.executescript(
        LEGACY_SCHEMA
        + "ALTER TABLE folders ADD COLUMN position INTEGER NOT NULL DEFAULT 0;"
        + "ALTER TABLE feeds ADD COLUMN position INTEGER NOT NULL DEFAULT 0;"
    )
    migrations.apply(conn)  # re-running migration 2 would fail with "duplicate column"
    assert version(conn) == migrations.latest_version()


def test_a_database_from_a_newer_app_is_refused():
    conn = memory_db()
    conn.execute(f"PRAGMA user_version = {migrations.latest_version() + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        migrations.apply(conn)


def test_a_failing_migration_rolls_back_completely(monkeypatch):
    monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS, "CREATE TABLE extra (id INTEGER); NOT VALID SQL;"])
    conn = memory_db()
    with pytest.raises(sqlite3.Error):
        migrations.apply(conn)
    assert version(conn) == len(migrations.MIGRATIONS) - 1
    assert not columns(conn, "extra")
