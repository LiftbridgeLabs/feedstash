"""`python -m app.cli backup`, which the README tells people to run with docker exec (as root)."""

import os
import sqlite3

import pytest

from app import cli
from app.errors import ReaderError


def make_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (42)")


def test_a_backup_copies_the_database_and_never_overwrites(tmp_path):
    make_db(tmp_path / "feedstash.db")
    target = tmp_path / "backups" / "one.db"
    cli._backup(tmp_path / "feedstash.db", target)
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    with pytest.raises(ReaderError, match="already exists"):
        cli._backup(tmp_path / "feedstash.db", target)


def test_run_as_root_the_backup_belongs_to_the_data_folders_owner(tmp_path, monkeypatch):
    make_db(tmp_path / "feedstash.db")
    owned = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: owned.append((str(path), uid, gid)))
    cli._backup(tmp_path / "feedstash.db", tmp_path / "backups" / "nested" / "two.db")
    owner = tmp_path.stat()
    assert owned == [(str(tmp_path / "backups"), owner.st_uid, owner.st_gid),
                     (str(tmp_path / "backups" / "nested"), owner.st_uid, owner.st_gid),
                     (str(tmp_path / "backups" / "nested" / "two.db"), owner.st_uid, owner.st_gid)]
