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
    sub: str  # "<provider>:<subject>" (google:…, oidc:…, local:<uuid>), or "dev-login"
    email: str
    name: str | None
    picture: str | None
    is_admin: bool = False
    has_password: bool = False
    created_at: int = 0


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


# ------------------------------------------------------------------ stash


@dataclass(frozen=True, slots=True)
class ItemLink:
    url: str
    label: str | None = None
    id: int | None = None  # None until stored


@dataclass(frozen=True, slots=True)
class StashItem:
    id: int
    type: str  # link | snippet | screenshot | email
    title: str | None
    content: str | None
    url: str | None
    image_name: str | None
    source: str
    reviewed: bool
    archived: bool
    created_at: int
    updated_at: int
    tags: list[str]
    links: list[ItemLink]  # the first is the primary link, mirrored in `url`


@dataclass(frozen=True, slots=True)
class ItemFilter:
    type: str | None = None
    tag: str | None = None
    reviewed: bool | None = None
    archived: bool = False
    query: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TagCount:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class StashSummary:
    inbox: int  # active and not yet reviewed
    total: int  # active
    archived: int
    by_type: dict[str, int]


@dataclass(frozen=True, slots=True)
class ApiToken:
    id: int
    client_name: str
    hint: str  # last four characters, for recognizing a token
    created_at: int
    last_used_at: int | None


@dataclass(frozen=True, slots=True)
class TokenMatch:
    token_id: int
    user_id: int
    client_name: str
