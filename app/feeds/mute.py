"""Muted words: deciding which articles a muted word catches (no I/O).

A word or phrase matches as whole words, ignoring case: "AI" catches "AI's new model" but not "said", and "apple
watch" catches "Apple  Watch" but not "Apple Watches". A muted article isn't hidden, it arrives already read, so every
device and app agrees on it without knowing about muting.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.db.models import MutedWord

MAX_PHRASE = 200


def clean(phrase: str) -> str:
    """Spaces collapsed and trimmed, as stored."""
    return " ".join(str(phrase or "").split())[:MAX_PHRASE]


def pattern(phrase: str) -> re.Pattern:
    words = clean(phrase).split(" ")
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)", re.IGNORECASE)


def applies_to(word: MutedWord, feed_id: int, folder_id: int | None) -> bool:
    if word.feed_id is not None:
        return word.feed_id == feed_id
    if word.folder_id is not None:
        return word.folder_id == folder_id
    return True


@dataclass(frozen=True, slots=True)
class Matcher:
    """The muted words for one feed, compiled once per refresh."""

    title_words: Sequence[re.Pattern]
    text_words: Sequence[re.Pattern]

    @classmethod
    def of(cls, words: Iterable[MutedWord]) -> "Matcher":
        words = list(words)
        return cls(
            title_words=[pattern(word.phrase) for word in words if word.title_only],
            text_words=[pattern(word.phrase) for word in words if not word.title_only],
        )

    @classmethod
    def for_feed(cls, words: Iterable[MutedWord], feed_id: int, folder_id: int | None) -> "Matcher":
        return cls.of(word for word in words if applies_to(word, feed_id, folder_id))

    def __bool__(self) -> bool:
        return bool(self.title_words or self.text_words)

    def mutes(self, title: str, text: str) -> bool:
        title = title or ""
        if any(word.search(title) for word in self.title_words):
            return True
        if self.text_words:
            both = f"{title}\n{text or ''}"
            return any(word.search(both) for word in self.text_words)
        return False
