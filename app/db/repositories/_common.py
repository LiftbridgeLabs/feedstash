import sqlite3
from collections.abc import Sequence
from typing import Literal

from app.errors import InvalidInput
from app.text import collapse_whitespace

MAX_NAME_LENGTH = 200


def clean_name(value: str | None, what: str) -> str:
    name = collapse_whitespace(value)
    if not name:
        raise InvalidInput(f"{what} can't be empty")
    return name[:MAX_NAME_LENGTH]


def next_position(
    conn: sqlite3.Connection,
    table: Literal["folders", "feeds", "stash_folders", "smart_lists", "stash_rules"],
    where: str,
    params: Sequence,
) -> int:
    """Position for a row appended to the end of an ordered list (folders, one folder's feeds, stash folders...)."""
    return conn.execute(f"SELECT COALESCE(MAX(position) + 1, 0) FROM {table} WHERE {where}", list(params)).fetchone()[0]


def ordered_ids(current: Sequence[int], requested: Sequence[int], allowed: set[int]) -> list[int]:
    """The requested order first, then anything the caller didn't mention, in its current order."""
    if len(set(requested)) != len(requested) or not set(requested) <= allowed:
        raise InvalidInput("Invalid ids")
    mentioned = set(requested)
    return [*requested, *(i for i in current if i not in mentioned)]
