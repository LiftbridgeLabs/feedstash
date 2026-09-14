"""Request and response shapes of the JSON API."""

from dataclasses import asdict, is_dataclass
from typing import TypeVar

from pydantic import BaseModel, Field

from app.db.models import ScopeKind


# ------------------------------------------------------------------ responses


class OkOut(BaseModel):
    ok: bool = True


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None
    picture: str | None


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


class RefreshIn(BaseModel):
    scope: ScopeKind = "all"
    id: int | None = None
