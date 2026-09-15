"""Request and response shapes of the JSON API."""

from dataclasses import asdict, is_dataclass
from typing import TypeVar

from pydantic import BaseModel, Field

from app.clock import iso
from app.db.models import ApiToken, ScopeKind, StashItem, User


# ------------------------------------------------------------------ responses


class OkOut(BaseModel):
    ok: bool = True


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None
    picture: str | None
    is_admin: bool
    has_password: bool
    read_retention_days: int


class AccountPrefsIn(BaseModel):
    read_retention_days: int = Field(ge=0, le=3650)  # 0 keeps read articles until the server's own cleanup


class AccountOut(BaseModel):
    id: int
    email: str
    name: str | None
    is_admin: bool
    has_password: bool
    sign_in: str  # how the account first signed in: password, google, oidc or dev
    created_at: int

    @classmethod
    def from_user(cls, user: User) -> "AccountOut":
        provider = user.sub.split(":", 1)[0] if ":" in user.sub else "dev"
        return cls(
            id=user.id, email=user.email, name=user.name, is_admin=user.is_admin, has_password=user.has_password,
            sign_in="password" if provider == "local" else provider, created_at=user.created_at,
        )


class FolderOut(BaseModel):
    id: int
    name: str
    position: int


class FeedOut(BaseModel):
    id: int
    folder_id: int | None
    title: str
    position: int
    url: str
    site_url: str | None
    last_fetched_at: int | None
    last_error: str | None
    unread: int


class TreeOut(BaseModel):
    folders: list[FolderOut]
    feeds: list[FeedOut]
    starred_count: int
    refresh_interval_minutes: int
    version: str  # the server's release, e.g. "0.1.4", or "dev"


class ArticleSummaryOut(BaseModel):
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


class ArticleOut(ArticleSummaryOut):
    content: str | None


class ArticlePageOut(BaseModel):
    articles: list[ArticleSummaryOut]
    next_cursor: str | None
    max_id: int


class CountOut(BaseModel):
    count: int


class UpdatedOut(BaseModel):
    updated: int


class StarredOut(BaseModel):
    starred: bool


class MarkedOut(BaseModel):
    marked: int
    batch: int


class RestoredOut(BaseModel):
    restored: int


class FolderOrderOut(BaseModel):
    ids: list[int]


class FeedOrderOut(BaseModel):
    folder_id: int | None
    ids: list[int]


class RefreshOut(BaseModel):
    feeds: int
    new: int


class ImportOut(BaseModel):
    added: int
    skipped: int
    folders_created: int


Out = TypeVar("Out", bound=BaseModel)


def to_schema(schema: type[Out], value) -> Out:
    """Builds a response model from a repository dataclass (nested dataclasses included)."""
    return schema.model_validate(asdict(value) if is_dataclass(value) else value)


# ------------------------------------------------------------------ requests


class PasswordLoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class SetupIn(BaseModel):
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=100)
    password: str = Field(max_length=1024)


class NewAccountIn(SetupIn):
    is_admin: bool = False


class AccountUpdateIn(BaseModel):
    password: str | None = Field(default=None, max_length=1024)
    is_admin: bool | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(default="", max_length=1024)
    new_password: str = Field(max_length=1024)


class ImportedLinkIn(BaseModel):
    url: str = Field(max_length=8000)
    title: str | None = Field(default=None, max_length=5000)
    saved_at: int | None = None  # Unix seconds
    tags: list[str] = Field(default_factory=list, max_length=20)
    reviewed: bool = False
    archived: bool = False


class ImportLinksIn(BaseModel):
    links: list[ImportedLinkIn] = Field(max_length=2000)


class ImportLinksOut(BaseModel):
    added: int
    already_saved: int
    invalid: int


class MarkArticlesIn(BaseModel):
    ids: list[int] = Field(max_length=2000)
    read: bool = True


class StarIn(BaseModel):
    starred: bool


class MarkScopeIn(BaseModel):
    scope: ScopeKind
    id: int | None = None
    older_than_hours: float | None = Field(default=None, gt=0)
    max_id: int | None = None


class UndoMarkIn(BaseModel):
    scope: ScopeKind
    id: int | None = None
    batch: int


class FolderIn(BaseModel):
    name: str


class ReorderIn(BaseModel):
    ids: list[int] = Field(max_length=5000)


class FeedReorderIn(ReorderIn):
    folder_id: int | None = None


class FollowIn(BaseModel):
    url: str
    folder_id: int | None = None
    folder_name: str | None = None
    title: str | None = None


class FeedUpdateIn(BaseModel):
    """Only fields present in the request are changed; `"folder_id": null` means Uncategorized."""

    title: str | None = None
    folder_id: int | None = None
    url: str | None = Field(default=None, max_length=4000)  # the feed's new address; fetched before it's accepted


class RefreshIn(BaseModel):
    scope: ScopeKind = "all"
    id: int | None = None


# ------------------------------------------------------------------ stash and API tokens
# Field names are camelCase: the browser extension, email worker and phone apps in clients/ decode these shapes.


class LinkOut(BaseModel):
    id: int
    url: str
    label: str | None


class StashItemOut(BaseModel):
    id: int
    type: str
    title: str | None
    content: str | None
    url: str | None  # mirrors links[0], for clients that only know one url
    imagePath: str | None
    source: str
    reviewed: bool
    archived: bool
    createdAt: str
    updatedAt: str
    tags: list[str]
    links: list[LinkOut]

    @classmethod
    def from_item(cls, item: StashItem) -> "StashItemOut":
        return cls(
            id=item.id, type=item.type, title=item.title, content=item.content, url=item.url,
            imagePath=f"/uploads/{item.image_name}" if item.image_name else None, source=item.source,
            reviewed=item.reviewed, archived=item.archived, createdAt=iso(item.created_at),
            updatedAt=iso(item.updated_at), tags=item.tags,
            links=[LinkOut(id=link.id, url=link.url, label=link.label) for link in item.links],
        )


class TagCountOut(BaseModel):
    name: str
    count: int


class StashSummaryOut(BaseModel):
    inbox: int
    total: int
    archived: int
    by_type: dict[str, int]


class StashArticleOut(BaseModel):
    item: StashItemOut
    created: bool


class TokenOut(BaseModel):
    id: int
    clientName: str
    tokenPreview: str
    createdAt: str
    lastUsedAt: str | None

    @classmethod
    def from_token(cls, token: ApiToken) -> "TokenOut":
        return cls(
            id=token.id, clientName=token.client_name, tokenPreview=f"...{token.hint}",
            createdAt=iso(token.created_at), lastUsedAt=iso(token.last_used_at) if token.last_used_at else None,
        )


class NewTokenIn(BaseModel):
    clientName: str


class NewTokenOut(BaseModel):
    id: int
    token: str
    clientName: str
