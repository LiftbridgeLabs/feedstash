"""Markers someone can write into what they send: `#tag` to tag it, `$Folder` to file it.

Used for mail, where there's no interface to click: the subject line can carry them, and so can any line of the
body that holds nothing else. That last rule keeps ordinary writing safe — a line reading "$5 off at Lowes" says
more than the marker, so it stays text.

    Subject: Deck plans $Backyard #diy        -> title "Deck plans", folder "Backyard", tag "diy"
    Subject: Paver notes $"Back yard project" -> a folder whose name has spaces

Folder names must start with a letter unless they're quoted, so "$5" is never a folder.
"""

import re
from dataclasses import dataclass

from app.text import collapse_whitespace

MAX_FOLDER = 200
_TAG = re.compile(r"#([\w-]+)")
_FOLDER = re.compile(r'\$(?:"([^"]{1,200})"|([A-Za-z][\w-]{0,199}))')


@dataclass(frozen=True, slots=True)
class Marked:
    title: str
    body: str
    folder: str | None
    tags: list[str]


def split_markers(subject: str, body: str = "") -> Marked:
    """Pulls the markers out of a subject and body, and gives back what's left to read."""
    title, folder, tags = _take(subject or "")
    kept = []
    for line in (body or "").splitlines():
        if not _only_markers(line):
            kept.append(line)
            continue
        _, line_folder, line_tags = _take(line)
        folder = folder or line_folder
        tags += [tag for tag in line_tags if tag not in tags]
    return Marked(title=collapse_whitespace(title), body="\n".join(kept).strip(), folder=folder, tags=tags)


def _take(text: str) -> tuple[str, str | None, list[str]]:
    tags: list[str] = []
    for match in _TAG.finditer(text):
        tag = match.group(1).lower()
        if tag not in tags:
            tags.append(tag)
    found = _FOLDER.search(text)  # the first one wins; an item lives in one folder
    folder = (found.group(1) or found.group(2)).strip()[:MAX_FOLDER] if found else None
    return _FOLDER.sub("", _TAG.sub("", text)), folder or None, tags


def _only_markers(line: str) -> bool:
    """A line that is nothing but markers, e.g. "$Backyard #diy"."""
    stripped = line.strip()
    if not stripped or not (_FOLDER.search(stripped) or _TAG.search(stripped)):
        return False
    return not _FOLDER.sub("", _TAG.sub("", stripped)).strip()
