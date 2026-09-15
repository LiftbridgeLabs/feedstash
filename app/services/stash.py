"""Capturing into the stash: validating input, storing images, and saving feed articles."""

import json
import logging
from dataclasses import dataclass, field

from app.clock import now
from app.db import Database
from app.db.models import ItemLink, PageJob, StashItem
from app.db.repositories import articles as articles_repo
from app.db.repositories import items as items_repo
from app.db.repositories import pages as pages_repo
from app.db.repositories import stash_rules
from app.errors import InvalidInput
from app.feeds import to_stash
from app.images import ImageStore
from app.pages.fetch import Page, extract
from app.services.pages import store_page

log = logging.getLogger("feedstash.stash")

MAX_TITLE = 1000
MAX_URL = 4000
MAX_SOURCE = 50
MAX_CONTENT = 1_000_000
MAX_LINKS = 100
MAX_PAGE_HTML = 5 * 1024 * 1024


def parse_tags(value) -> list[str]:
    """Tags arrive as a list, a JSON array string (phone apps, email worker) or comma-separated text."""
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [str(tag) for tag in value]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(tag) for tag in parsed]
    return text.split(",")


def parse_links(value) -> list[ItemLink] | None:
    """Links arrive as a list of URLs or {url, label} objects, a JSON string of either (multipart forms can't send
    lists), or one URL per line. None means the field wasn't sent, which differs from an empty list."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except ValueError:
            value = text.splitlines()
    if not isinstance(value, list | tuple):
        value = [value]
    links = []
    for entry in value:
        url, label = (entry.get("url"), entry.get("label")) if isinstance(entry, dict) else (entry, None)
        if url := _line(url, MAX_URL):
            links.append(ItemLink(url=url, label=_line(label, MAX_TITLE)))
    if len(links) > MAX_LINKS:
        raise InvalidInput(f"An item can have at most {MAX_LINKS} links")
    return links


def parse_folder_id(value) -> int | None:
    """A stash folder's id, from JSON (a number, or null for none) or a form field (text; empty for none)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise InvalidInput("folderId must be a folder's id")
    try:
        folder_id = int(value)
    except (TypeError, ValueError):
        raise InvalidInput("folderId must be a folder's id") from None
    if folder_id <= 0:
        raise InvalidInput("folderId must be a folder's id")
    return folder_id


def _line(value, limit: int) -> str | None:
    """A single-line field: trimmed, clipped, empty becomes None."""
    if value is None:
        return None
    return str(value).strip()[:limit] or None


def _body(value) -> str | None:
    """Free text keeps its whitespace (snippets can be code), but blank becomes None."""
    if value is None or not str(value).strip():
        return None
    return str(value)[:MAX_CONTENT]


@dataclass(frozen=True, slots=True)
class Capture:
    type: str
    title: str | None = None
    content: str | None = None
    url: str | None = None
    source: str | None = None
    tags: list[str] = field(default_factory=list)
    image: bytes | None = None
    links: list[ItemLink] = field(default_factory=list)
    folder_id: int | None = None
    # The page as the client saw it (the browser extension sends the open tab), for sites that block servers.
    page_html: str | None = None

    @classmethod
    def from_fields(cls, fields: dict, *, image: bytes | None = None) -> "Capture":
        page_html = fields.get("pageHtml")
        return cls(
            type=str(fields.get("type") or "").strip(),
            title=_line(fields.get("title"), MAX_TITLE),
            content=_body(fields.get("content")),
            url=_line(fields.get("url"), MAX_URL),
            links=parse_links(fields.get("links")) or [],
            source=_line(fields.get("source"), MAX_SOURCE),
            tags=parse_tags(fields.get("tags")),
            image=image or None,
            folder_id=parse_folder_id(fields.get("folderId")),
            page_html=page_html[:MAX_PAGE_HTML] if isinstance(page_html, str) and page_html.strip() else None,
        )


def _check(capture: Capture) -> None:
    if capture.type not in items_repo.ITEM_TYPES:
        raise InvalidInput(f"type must be one of: {', '.join(items_repo.ITEM_TYPES)}")
    if capture.type == "link" and not (capture.url or capture.links):
        raise InvalidInput("A link needs a url")
    if capture.type == "snippet" and not (capture.content or capture.links):
        raise InvalidInput("A snippet needs content or a link")
    if capture.type == "screenshot" and not capture.image:
        raise InvalidInput("A screenshot needs an image")
    if capture.type == "email" and not (capture.title or capture.content):
        raise InvalidInput("An email needs a subject or a body")


def _sent_page(capture: Capture) -> Page | None:
    """Extracts the page a client sent along. A page that can't be read is ignored: the server fetches it instead."""
    url = capture.url or (capture.links[0].url if capture.links else None)
    if not capture.page_html or not pages_repo.is_web_url(url):
        return None
    try:
        return extract(capture.page_html, url)
    except Exception:
        log.warning("Couldn't read the page sent with %s", url, exc_info=True)
        return None


def capture(db: Database, images: ImageStore, user_id: int, item: Capture, *, default_source: str) -> StashItem:
    _check(item)
    page = _sent_page(item)  # before the transaction: extracting can take a moment
    image_name = images.save(item.image) if item.image else None
    try:
        with db.transaction() as conn:
            timestamp = now()
            created = items_repo.create(
                conn, user_id, type=item.type, title=item.title, content=item.content, url=item.url,
                links=item.links, image_name=image_name, source=item.source or default_source, tags=item.tags,
                now=timestamp, folder_id=item.folder_id,
            )
            stash_rules.apply(conn, user_id, created.id, now=timestamp)
            if page is not None and pages_repo.is_web_url(created.url):
                store_page(conn, PageJob(item_id=created.id, url=created.url, attempts=1), page, now=timestamp)
            return items_repo.get(conn, user_id, created.id)
    except BaseException:
        images.delete(image_name)  # don't leave an orphaned file behind
        raise


def update(db: Database, user_id: int, item_id: int, fields: dict) -> StashItem:
    """Applies the fields present in a PATCH body: title, content, url, links, reviewed, archived, tags, folderId."""
    changes: dict = {}
    if "title" in fields:
        changes["title"] = _line(fields["title"], MAX_TITLE)
    if "url" in fields:
        changes["url"] = _line(fields["url"], MAX_URL)
    if "content" in fields:
        changes["content"] = _body(fields["content"])
    for flag in ("reviewed", "archived"):
        if fields.get(flag) is not None:
            changes[flag] = bool(fields[flag])
    if fields.get("tags") is not None:
        changes["tags"] = parse_tags(fields["tags"])
    if (links := parse_links(fields.get("links"))) is not None:
        changes["links"] = links
    if "folderId" in fields:
        changes["folder_id"] = parse_folder_id(fields["folderId"])
    with db.transaction() as conn:
        return items_repo.update(conn, user_id, item_id, now=now(), **changes)


def remove(db: Database, images: ImageStore, user_id: int, item_id: int) -> None:
    with db.transaction() as conn:
        image_name = items_repo.delete(conn, user_id, item_id)
    images.delete(image_name)


def stash_article(db: Database, user_id: int, article_id: int) -> tuple[StashItem, bool]:
    """Saves a feed article as a link. Returns the item and whether it was newly created."""
    with db.transaction() as conn:
        article = articles_repo.get(conn, user_id, article_id)
        return to_stash.stash_article(conn, user_id, article, now=now())
