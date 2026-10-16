"""Importing saved links in bulk: bookmarks exported from Feedly boards, a browser, Pocket or Raindrop.

The browser reads the exported files and sends the links the user chose; this checks them and adds the new ones.
"""

from dataclasses import dataclass, field

from app.clock import now
from app.db import Database
from app.db.repositories import items as items_repo
from app.errors import InvalidInput

MAX_LINKS_PER_REQUEST = 2000
IMPORT_BATCH = 200
MAX_TITLE = 1000
MAX_URL = 4000
EARLIEST_SAVE = 631152000  # 1990-01-01; an older "saved" date is treated as unknown


@dataclass(frozen=True, slots=True)
class ImportedLink:
    url: str
    title: str | None = None
    saved_at: int | None = None  # Unix seconds
    tags: list[str] = field(default_factory=list)
    reviewed: bool = False
    archived: bool = False


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int
    already_saved: int
    invalid: int


def import_links(db: Database, user_id: int, links: list[ImportedLink]) -> ImportResult:
    """Adds each http(s) link the user doesn't already have, keeping its saved date, tags and destination."""
    if len(links) > MAX_LINKS_PER_REQUEST:
        raise InvalidInput(f"Send at most {MAX_LINKS_PER_REQUEST} links at a time")
    current = now()
    valid, invalid = [], 0
    for link in links:
        url = (link.url or "").strip()
        if url.lower().startswith(("http://", "https://")) and len(url) <= MAX_URL:
            valid.append((url, link))
        else:
            invalid += 1

    added = already_saved = 0
    seen: set[str] = set()
    # A batch per transaction: two thousand links in one would hold SQLite's only write lock long enough to stall
    # feed refreshes, page saving and everyone else's saves.
    for start in range(0, len(valid), IMPORT_BATCH):
        batch = valid[start:start + IMPORT_BATCH]
        with db.transaction() as conn:
            # Checked per batch, inside its transaction: something may have been saved since the last one.
            seen |= items_repo.existing_link_urls(conn, user_id, [url for url, _ in batch])
            for url, link in batch:
                if url in seen:
                    already_saved += 1
                    continue
                seen.add(url)
                saved_at = link.saved_at if link.saved_at and EARLIEST_SAVE <= link.saved_at <= current else current
                items_repo.create(
                    conn, user_id, type="link", title=(link.title or "").strip()[:MAX_TITLE] or None, content=None,
                    url=url, source="import", tags=link.tags, now=saved_at,
                    reviewed=link.reviewed or link.archived, archived=link.archived,
                )
                added += 1
    return ImportResult(added=added, already_saved=already_saved, invalid=invalid)
