"""Storage: what counts toward STORAGE_LIMIT_GB."""

from pathlib import Path

import pytest

from app.errors import StorageFull
from app.storage import Storage, _size


def test_the_database_and_pictures_count_and_are_remeasured_each_minute(tmp_path):
    clock = [0.0]
    (tmp_path / "feedstash.db").write_bytes(b"x" * 600)
    (tmp_path / "feedstash.db-wal").write_bytes(b"x" * 100)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "a.png").write_bytes(b"x" * 300)
    storage = Storage(tmp_path / "feedstash.db", tmp_path / "uploads", 1000 / 1024 ** 3, clock=lambda: clock[0])
    assert storage.used() == 1000 and storage.full
    with pytest.raises(StorageFull):
        storage.check()
    (tmp_path / "uploads" / "a.png").unlink()
    assert storage.used() == 1000  # measured at most once a minute
    clock[0] = 60
    assert storage.used() == 700 and not storage.full


def test_a_file_gone_since_it_was_listed_counts_as_nothing(tmp_path):
    assert _size(Path(tmp_path / "feedstash.db-journal")) == 0
