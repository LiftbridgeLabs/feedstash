import sqlite3

import pytest

from app.db import migrations
from app.db.repositories import users


@pytest.fixture
def conn():
    """An in-memory database with the current schema."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrations.apply(connection)
    yield connection
    connection.close()


@pytest.fixture
def user_id(conn) -> int:
    return users.upsert(conn, sub="sub-ann", email="ann@example.com", name="Ann", picture=None)
