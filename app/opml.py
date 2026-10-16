"""The OPML subscription-list format. Pure functions: no database, no network."""

from collections.abc import Sequence
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml import ElementTree

from app.db.models import Feed, Folder


def parse_opml(data: bytes) -> list[tuple[str | None, str, str | None]]:
    """Returns (folder_name, feed_url, title) in file order. Nested folders are flattened into their
    top-level folder, the same way Feedly exports them."""
    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:
        raise ValueError("That file isn't valid OPML") from exc
    body = root.find("body")
    if body is None:
        raise ValueError("That file isn't valid OPML (no <body>)")

    results: list[tuple[str | None, str, str | None]] = []

    # An explicit stack of iterators, not recursion: a file nested thousands of levels deep would otherwise crash
    # the import with a RecursionError. Same order as the file; the outermost named outline is the folder.
    stack = [(iter(body.findall("outline")), None)]
    while stack:
        outlines, folder = stack[-1]
        outline = next(outlines, None)
        if outline is None:
            stack.pop()
            continue
        url = outline.get("xmlUrl") or outline.get("xmlurl")
        title = outline.get("title") or outline.get("text")
        if url:
            results.append((folder, url.strip(), title))
        else:
            stack.append((iter(outline.findall("outline")), folder or (title or "").strip() or None))
    return results


def build_opml(folders: Sequence[Folder], feeds: Sequence[Feed]) -> bytes:
    """Serializes folders and feeds, in the order given."""
    document = Element("opml", version="2.0")
    SubElement(SubElement(document, "head"), "title").text = "Reader subscriptions"
    body = SubElement(document, "body")

    def add_feed(parent: Element, feed: Feed) -> None:
        attrs = {"type": "rss", "text": feed.title, "title": feed.title, "xmlUrl": feed.url}
        if feed.site_url:
            attrs["htmlUrl"] = feed.site_url
        SubElement(parent, "outline", attrs)

    for folder in folders:
        node = SubElement(body, "outline", text=folder.name, title=folder.name)
        for feed in feeds:
            if feed.folder_id == folder.id:
                add_feed(node, feed)
    for feed in feeds:
        if feed.folder_id is None:
            add_feed(body, feed)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(document, encoding="utf-8")
