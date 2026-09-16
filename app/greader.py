"""The names the Google Reader API uses, and turning them into FeedStash's own. No I/O.

There's no official spec: Google shut Reader down in 2013 and the protocol lived on because every reader app had
already implemented it. This follows what FreshRSS and Miniflux implement, since that's what the apps are tested
against.
"""

import re

READING_LIST = "user/-/state/com.google/reading-list"
READ = "user/-/state/com.google/read"
STARRED = "user/-/state/com.google/starred"
LABEL = "user/-/label/"
ITEM_PREFIX = "tag:google.com,2005:reader/item/"
_USER = re.compile(r"^user/[^/]+/")


def auth_token(header: str) -> str | None:
    """The token in `Authorization: GoogleLogin auth=<token>`. A plain bearer token works too."""
    scheme, _, value = (header or "").strip().partition(" ")
    scheme = scheme.lower()
    if scheme == "googlelogin":
        key, _, token = value.strip().partition("=")
        if key.strip().lower() != "auth":
            return None
        return token.strip() or None
    if scheme == "bearer":
        return value.strip() or None
    return None


def normalize_stream(stream: str | None) -> str:
    """Some clients put their user id where Reader puts "-"; both mean the signed-in account."""
    return _USER.sub("user/-/", (stream or "").strip())


def parse_stream(stream: str | None) -> tuple[str, str | None]:
    """A stream id as (kind, value): reading-list, read, starred, label (a folder name), feed, or unknown."""
    stream = normalize_stream(stream)
    if stream == READING_LIST:
        return "reading-list", None
    if stream == READ:
        return "read", None
    if stream == STARRED:
        return "starred", None
    if stream.startswith(LABEL):
        return "label", stream[len(LABEL):]
    if stream.startswith("feed/"):
        return "feed", stream[len("feed/"):]
    return "unknown", None


def label_stream(name: str) -> str:
    return f"{LABEL}{name}"


def label_name(stream: str | None) -> str | None:
    """The folder name in a label stream, or None for any other kind of stream."""
    stream = normalize_stream(stream)
    if not stream.startswith(LABEL):
        return None
    return stream[len(LABEL):] or None


def feed_stream(feed_id: int) -> str:
    return f"feed/{feed_id}"


def item_id(article_id: int) -> str:
    """The long form clients get back: a 16-digit hex number behind Google's tag prefix."""
    return f"{ITEM_PREFIX}{article_id:016x}"


def parse_item_id(value: str | None) -> int | None:
    """Clients send an item id in whichever form they kept: the long tagged form, the bare 16-digit hex, or a
    decimal number. Sixteen characters is always hex, even when every one of them is a digit."""
    value = (value or "").strip()
    try:
        if value.startswith(ITEM_PREFIX):
            return int(value[len(ITEM_PREFIX):], 16)
        if len(value) == 16:
            return int(value, 16)
        if value.isdigit():
            return int(value)
    except ValueError:
        return None
    return None


def item(article, feed, folder_names: dict[int, str]) -> dict:
    """An article as Reader clients expect it. Read and starred state travel as categories."""
    categories = [READING_LIST]
    if article.read:
        categories.append(READ)
    if article.starred:
        categories.append(STARRED)
    if feed is not None and feed.folder_id in folder_names:
        categories.append(label_stream(folder_names[feed.folder_id]))
    published = article.published_at
    links = [{"href": article.url, "type": "text/html"}] if article.url else []
    return {
        "id": item_id(article.id),
        "crawlTimeMsec": str(published * 1000),
        "timestampUsec": str(published * 1_000_000),
        "published": published,
        "updated": published,
        "title": article.title,
        "canonical": [{"href": article.url}] if article.url else [],
        "alternate": links,
        "categories": categories,
        "origin": {
            "streamId": feed_stream(article.feed_id),
            "title": article.feed_title,
            "htmlUrl": article.site_url or "",
        },
        "summary": {"direction": "ltr", "content": article.content or article.summary or ""},
        "author": article.author or "",
    }
