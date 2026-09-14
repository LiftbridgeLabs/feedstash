"""Persistence: SQLite connections, schema migrations, and one repository module per table."""

from app.db.database import Database

__all__ = ["Database"]
