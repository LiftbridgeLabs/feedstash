"""Plain data objects passed between the repositories and the rest of the app."""

from dataclasses import dataclass, field
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
    sub: str  # "<provider>:<subject>" (google:…, oidc:…, oidc@<issuer>:…, local:<uuid>), or "dev-login"
    email: str
    name: str | None
    picture: str | None
    is_admin: bool = False
    has_password: bool = False
    created_at: int = 0
    read_retention_days: int = 30  # read articles are deleted this long after reading; 0 = only the server's cleanup
    sections: str = "both"  # which halves of the app they use: both, feeds or stash


@dataclass(frozen=True, slots=True)
class SignInProvider:
    """A sign-in added in Settings → Sign-in. `client_secret` is as stored: encrypted with the server's SecretBox."""

    id: int
    kind: str  # "google" or "oidc"
    name: str  # what the button says after "Sign in with"
    issuer: str  # the OIDC issuer (or its discovery document's URL); Google's for kind "google"
    client_id: str
    client_secret: str
    scopes: str
    icon: str  # "key", "shield", "lock", "none", or an image's address
    color: str  # "#rrggbb", or "" for the theme's
    enabled: bool
    position: int
    updated_at: int


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
    auto_stash: bool = False  # new articles go straight to the stash
    full_text: bool = False  # new articles get the full page fetched, for feeds that only send a summary
    last_new_at: int | None = None  # when it last brought in a new article


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
    search_text: str = ""  # the article as plain text, for the search index


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
    full_content: str | None = None  # the article's page, extracted, once fetched


@dataclass(frozen=True, slots=True)
class FullTextJob:
    """An article whose page should be fetched for its full text."""

    article_id: int
    url: str


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
class PagePreview:
    """What has been saved of the web page behind an item."""

    status: str  # pending | working | ready | failed | skipped
    title: str | None
    description: str | None
    image_url: str | None
    site_name: str | None
    has_copy: bool
    fetched_at: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class PageCopy:
    url: str
    status: str
    title: str | None
    html: str | None
    fetched_at: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class PageJob:
    """A page claimed for fetching."""

    item_id: int
    url: str
    attempts: int  # including this one


@dataclass(frozen=True, slots=True)
class StashItem:
    id: int
    type: str  # link | snippet | screenshot | email
    title: str | None
    content: str | None
    url: str | None
    image_name: str | None  # the first picture
    source: str
    reviewed: bool
    archived: bool
    created_at: int
    updated_at: int
    tags: list[str]
    links: list[ItemLink]  # the first is the primary link, mirrored in `url`
    page: PagePreview | None = None  # None when the item has no web address
    folder_id: int | None = None
    feed_id: int | None = None  # the feed it was saved from
    image_names: list[str] = field(default_factory=list)  # every picture, in order; image_name is the first


@dataclass(frozen=True, slots=True)
class ItemFilter:
    type: str | None = None
    tag: str | None = None
    reviewed: bool | None = None
    archived: bool = False
    query: str | None = None
    folder_id: int | None = None
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
class StashFolder:
    id: int
    name: str
    position: int
    count: int = 0  # active (not archived) items in it


@dataclass(frozen=True, slots=True)
class SmartList:
    """A saved stash search, shown in the sidebar."""

    id: int
    name: str
    position: int
    query: str | None
    type: str | None
    tag: str | None
    folder_id: int | None


@dataclass(frozen=True, slots=True)
class StashRule:
    """When a new stash item matches `field` and `value`, tag it, file it, mark it reviewed and/or archive it."""

    id: int
    field: str  # domain | url | title | text | feed | type
    value: str
    add_tag: str | None
    folder_id: int | None
    mark_reviewed: bool
    archive: bool


@dataclass(frozen=True, slots=True)
class MailAccount:
    """A mailbox FeedStash checks: anything forwarded there becomes a stash item."""

    id: int
    user_id: int
    host: str
    port: int
    username: str
    password: str  # encrypted; the service decrypts it with the server's secret key
    folder: str
    allowed_senders: list[str]  # empty means anything in the mailbox is saved
    enabled: bool
    last_checked_at: int | None
    last_error: str | None
    saved_count: int


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
