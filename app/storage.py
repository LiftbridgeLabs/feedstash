"""How much of the server's storage limit (STORAGE_LIMIT_GB) is in use: the database and uploaded pictures.

Measured at most once a minute, since walking the uploads folder isn't free; a save just past the limit can slip
through within that minute, which is fine for a guard against filling the disk.
"""

import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.errors import StorageFull

GB = 1024 ** 3
REMEASURE_SECONDS = 60


class Storage:
    def __init__(self, database: Path, uploads: Path, limit_gb: float, clock: Callable[[], float] = time.monotonic):
        self.database = database
        self.uploads = uploads
        self.limit_bytes = int(limit_gb * GB)
        self._clock = clock
        self._measured_at: float | None = None
        self._used = 0
        self._lock = threading.Lock()

    def used(self) -> int:
        with self._lock:
            if self._measured_at is None or self._clock() - self._measured_at >= REMEASURE_SECONDS:
                self._used = self._measure()
                self._measured_at = self._clock()
            return self._used

    def _measure(self) -> int:
        paths = list(self.database.parent.glob(self.database.name + "*"))  # the database and its -wal / -shm
        if self.uploads.is_dir():
            paths += self.uploads.iterdir()
        return sum(_size(path) for path in paths)

    @property
    def full(self) -> bool:
        return bool(self.limit_bytes) and self.used() >= self.limit_bytes

    def check(self) -> None:
        """Raises StorageFull when the server is at its limit."""
        if self.full:
            limit = f"{self.limit_bytes / GB:g} GB"
            raise StorageFull(f"This server's storage is full ({limit}). Delete some saved items or pictures to make "
                              "room, or ask whoever runs it for more.")


def _size(path: Path) -> int:
    """A file's size; 0 for a folder or a file removed since it was listed (SQLite's -journal comes and goes)."""
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0
