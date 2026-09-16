"""Turns a raw email into the parts a stash item needs. No I/O, no database."""

import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.utils import parseaddr

from app.images import MAX_IMAGE_BYTES
from app.text import collapse_whitespace, html_to_text

MAX_TITLE = 1000
MAX_BODY = 1_000_000
MAX_LINKS = 10
# What every newsletter carries and nobody wants saved as the article.
BORING_LINK = re.compile(r"unsubscribe|list-manage|/preferences|/privacy|\.gif($|\?)", re.I)
_HREF = re.compile(r"href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_BARE_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_HASHTAG = re.compile(r"#([\w-]+)")


@dataclass(frozen=True, slots=True)
class ParsedMail:
    message_id: str
    sender: str  # lowercase address, "" when the message doesn't say
    title: str
    tags: list[str] = field(default_factory=list)
    body: str = ""
    links: list[str] = field(default_factory=list)
    image: bytes | None = None


def parse_message(raw: bytes) -> ParsedMail:
    message = message_from_bytes(raw, policy=policy.default)
    subject = collapse_whitespace(str(message.get("Subject", ""))) or "(no subject)"
    title, tags = _split_hashtags(subject)
    text, html = _bodies(message)
    return ParsedMail(
        message_id=str(message.get("Message-ID", "")).strip(),
        sender=parseaddr(str(message.get("From", "")))[1].lower(),
        title=title[:MAX_TITLE],
        tags=tags,
        body=(text or html_to_text(html))[:MAX_BODY],
        links=_links(text, html),
        image=_first_image(message),
    )


def sender_allowed(sender: str, allowed: list[str]) -> bool:
    """Entries are whole addresses, whole domains ("@example.com"), or "*". Empty allows anything."""
    if not allowed or "*" in allowed:
        return True
    domain = sender[sender.find("@"):] if "@" in sender else ""
    return sender in allowed or (bool(domain) and domain in allowed)


def _split_hashtags(subject: str) -> tuple[str, list[str]]:
    """"Reef guide #diving #reading" -> ("Reef guide", ["diving", "reading"])."""
    tags = [tag.lower() for tag in _HASHTAG.findall(subject)]
    title = collapse_whitespace(_HASHTAG.sub("", subject))
    return (title or subject), tags


def _bodies(message) -> tuple[str, str]:
    """The message's plain text and HTML parts, ignoring attachments."""
    text = html = ""
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        subtype = part.get_content_subtype()
        if subtype not in ("plain", "html"):
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):  # an encoding Python doesn't know
            continue
        if subtype == "plain" and not text:
            text = content.strip()
        elif subtype == "html" and not html:
            html = content
    return text, html


def _links(text: str, html: str) -> list[str]:
    """Addresses the message points at, the HTML's own links first."""
    found: list[str] = []
    for candidate in [*_HREF.findall(html), *_BARE_URL.findall(text)]:
        url = candidate.strip().rstrip("),.")
        if not url.lower().startswith(("http://", "https://")) or len(url) > 2000:
            continue
        if BORING_LINK.search(url) or url in found:
            continue
        found.append(url)
        if len(found) == MAX_LINKS:
            break
    return found


def _first_image(message) -> bytes | None:
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() != "image":
            continue
        content = part.get_payload(decode=True)
        if content and len(content) <= MAX_IMAGE_BYTES:
            return content
    return None
