"""Plain data objects passed between the repositories and the rest of the app."""

from dataclasses import dataclass
from typing import Literal

ScopeKind = Literal["all", "starred", "folder", "feed", "uncategorized"]
SortOrder = Literal["newest", "oldest"]


@dataclass(frozen=True, slots=True)
class Scope:
    """A sidebar selection: All, Read later, Uncategorized, one folder, or one feed."""

    kind: ScopeKind = "all"
    id: int | None = None


@dataclass(frozen=True, slots=True)
class User:
    id: int
    sub: str
    email: str
    name: str | None
    picture: str | None


@dataclass(frozen=True, slots=True)
class Folder:
    id: int
    name: str
    position: int


@dataclass(frozen=True, slots=True)
class Feed:
    id: int
    folder_id: int | None
    title: str
    position: int
    url: str
    site_url: str | None
    last_fetched_at: int | None
    last_error: str | None
    unread: int


@dataclass(frozen=True, slots=True)
class FeedFetchState:
    """What the refresher needs to know about a feed."""

    id: int
    url: str
    etag: str | None
    last_modified: str | None
    last_fetched_at: int | None


@dataclass(frozen=True, slots=True)
class NewArticle:
    guid: str
    title: str
    url: str | None
    author: str | None
    summary: str
    content: str
    image: str | None
    published_at: int


@dataclass(frozen=True, slots=True)
class ArticleSummary:
    id: int
    feed_id: int
    title: str
    url: str | None
    author: str | None
    summary: str | None
    image: str | None
    published_at: int
    read: bool
    starred: bool
    feed_title: str
    site_url: str | None


@dataclass(frozen=True, slots=True)
class Article(ArticleSummary):
    content: str | None


@dataclass(frozen=True, slots=True)
class ArticlePage:
    articles: list[ArticleSummary]
    next_cursor: str | None
    max_id: int
