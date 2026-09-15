import time
from datetime import UTC, datetime


def now() -> int:
    """Current Unix time in whole seconds, the unit stored in the database."""
    return int(time.time())


def iso(timestamp: int) -> str:
    """UTC ISO-8601 with milliseconds (2026-01-02T03:04:05.000Z), the format the phone apps expect."""
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
