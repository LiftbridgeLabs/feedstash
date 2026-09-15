import html
import re

_TAG_RE = re.compile(r"<[^>]+>")


def collapse_whitespace(value: str | None) -> str:
    """Trims and squeezes runs of whitespace to single spaces."""
    return " ".join((value or "").split())


def html_to_text(value: str | None, limit: int = 200_000) -> str:
    """Plain text from an HTML fragment, for search: tags become spaces and entities are decoded."""
    return collapse_whitespace(html.unescape(_TAG_RE.sub(" ", value or "")))[:limit]
