"""Turns RSS/Atom documents into plain data. No network, no database."""

import calendar
import hashlib
import html
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import feedparser

MAX_ENTRIES = 250
FEED_LINK_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "application/rdf+xml"})

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_IMG_RE = re.compile(r"""<img[^>]+?src\s*=\s*["']([^"']+)["']""", re.I)


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    guid: str
    title: str
    url: str | None
    author: str | None
    summary: str
    content: str
    image: str | None
    published_at: int | None  # None when the feed gives no date


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    title: str
    site_url: str | None
    entries: list[ParsedEntry]


def parse_feed(content: bytes, url: str, content_type: str | None = None, *, now: int | None = None) -> ParsedFeed | None:
    """Parses a feed, or returns None if the document isn't RSS or Atom.

    feedparser sanitizes entry HTML (scripts, event handlers, iframes...) and resolves relative links
    against `url`. Dates in the future are clamped to `now`.
    """
    parsed = feedparser.parse(
        content, response_headers={"content-location": url, "content-type": content_type or "application/xml"}
    )
    if not (parsed.get("version") or parsed.entries):
        return None
    now = int(time.time()) if now is None else now
    return ParsedFeed(
        title=plain_text(parsed.feed.get("title") or "", 200) or urlparse(url).netloc,
        site_url=http_url(parsed.feed.get("link")),
        entries=[_entry(entry, now) for entry in parsed.entries[:MAX_ENTRIES]],
    )


MAX_FEED_LINKS = 10  # a real page advertises a handful; each one is fetched in turn while someone waits


def find_feed_links(page: str, base_url: str) -> list[str]:
    """Absolute URLs of the feeds an HTML page advertises with <link rel="alternate">, the first few, without
    repeats."""
    finder = _FeedLinkFinder()
    try:
        finder.feed(page)
    except Exception:  # malformed HTML: keep whatever was found before the error
        pass
    links = list(dict.fromkeys(urljoin(base_url, href) for href in finder.links))
    return links[:MAX_FEED_LINKS]


def plain_text(value: str, limit: int) -> str:
    text = _WHITESPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value or ""))).strip()
    return text[: limit - 1].rstrip() + "…" if len(text) > limit else text


def http_url(value: str | None) -> str | None:
    return value if value and value.lower().startswith(("http://", "https://")) else None


# ------------------------------------------------------------------ internals


class _FeedLinkFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attr = {name.lower(): (value or "") for name, value in attrs}
        if (
            "alternate" in attr.get("rel", "").lower().split()
            and attr.get("type", "").lower() in FEED_LINK_TYPES
            and attr.get("href")
        ):
            self.links.append(attr["href"])


def _entry(entry, now: int) -> ParsedEntry:
    content = _content_html(entry)
    title = plain_text(entry.get("title") or "", 500)
    link = http_url(entry.get("link"))
    guid = entry.get("id") or link
    if not guid:
        guid = hashlib.sha1(f"{title}|{entry.get('published', '')}|{content[:500]}".encode()).hexdigest()
    return ParsedEntry(
        guid=guid[:2000],
        title=title or "(untitled)",
        url=link,
        author=plain_text(entry.get("author") or "", 200) or None,
        summary=plain_text(content, 400),
        content=content,
        image=_image(entry, content),
        published_at=_timestamp(entry, now),
    )


def _detail_html(detail) -> str:
    value = detail.get("value") or ""
    if (detail.get("type") or "") == "text/plain":
        return html.escape(value).replace("\n", "<br>")
    return value


def _content_html(entry) -> str:
    candidates = [_detail_html(item) for item in entry.get("content") or []]
    if entry.get("summary_detail"):
        candidates.append(_detail_html(entry.summary_detail))
    elif entry.get("summary"):
        candidates.append(entry.summary)
    return max(candidates, key=len, default="")


def _image(entry, content: str) -> str | None:
    for media in entry.get("media_thumbnail") or []:
        if http_url(media.get("url")):
            return media["url"]
    for media in entry.get("media_content") or []:
        is_image = media.get("medium") == "image" or (media.get("type") or "").startswith("image/")
        if is_image and http_url(media.get("url")):
            return media["url"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/") and http_url(link.get("href")):
            return link["href"]
    match = _IMG_RE.search(content or "")
    return http_url(html.unescape(match.group(1))) if match else None


def _timestamp(entry, now: int) -> int | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return min(calendar.timegm(value), now)
            except (TypeError, ValueError, OverflowError):
                continue
    return None
