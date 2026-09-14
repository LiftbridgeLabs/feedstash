from typing import Annotated

from fastapi import APIRouter, Query

from app.clock import now
from app.db.models import Scope, ScopeKind, SortOrder
from app.db.repositories import articles as articles_repo
from app.web.deps import DatabaseDep, UserDep
from app.web.schemas import (
    ArticleOut,
    ArticlePageOut,
    CountOut,
    MarkArticlesIn,
    MarkedOut,
    MarkScopeIn,
    RestoredOut,
    StarIn,
    StarredOut,
    UndoMarkIn,
    UpdatedOut,
    to_schema,
)

router = APIRouter(prefix="/api")

# The query parameter is called `id`; renamed here so it doesn't shadow the builtin.
ScopeId = Annotated[int | None, Query(alias="id")]


@router.get("/articles", response_model=ArticlePageOut)
def list_articles(
    user: UserDep,
    db: DatabaseDep,
    scope: ScopeKind = "all",
    scope_id: ScopeId = None,
    unread_only: bool = True,
    order: SortOrder = "newest",
    cursor: str | None = None,
    max_id: int | None = None,
    limit: int = 40,
) -> ArticlePageOut:
    with db.transaction() as conn:
        page = articles_repo.page(
            conn, user.id, Scope(scope, scope_id),
            unread_only=unread_only, order=order, cursor=cursor, max_id=max_id, limit=limit,
        )
    return to_schema(ArticlePageOut, page)


# Declared before /articles/{article_id} so "new-count" isn't parsed as an id.
@router.get("/articles/new-count", response_model=CountOut)
def count_new_articles(
    user: UserDep, db: DatabaseDep, scope: ScopeKind = "all", scope_id: ScopeId = None,
    since_id: int = 0, unread_only: bool = True,
) -> CountOut:
    with db.transaction() as conn:
        count = articles_repo.count_new(conn, user.id, Scope(scope, scope_id), since_id=since_id, unread_only=unread_only)
    return CountOut(count=count)


@router.get("/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, user: UserDep, db: DatabaseDep) -> ArticleOut:
    with db.transaction() as conn:
        return to_schema(ArticleOut, articles_repo.get(conn, user.id, article_id))


@router.post("/articles/mark", response_model=UpdatedOut)
def mark_articles(body: MarkArticlesIn, user: UserDep, db: DatabaseDep) -> UpdatedOut:
    with db.transaction() as conn:
        updated = articles_repo.set_read(conn, user.id, body.ids, read=body.read, now=now())
    return UpdatedOut(updated=updated)


@router.post("/articles/{article_id}/star", response_model=StarredOut)
def star_article(article_id: int, body: StarIn, user: UserDep, db: DatabaseDep) -> StarredOut:
    with db.transaction() as conn:
        articles_repo.set_starred(conn, user.id, article_id, starred=body.starred, now=now())
    return StarredOut(starred=body.starred)


@router.post("/mark-read", response_model=MarkedOut)
def mark_scope_read(body: MarkScopeIn, user: UserDep, db: DatabaseDep) -> MarkedOut:
    batch = now()
    published_before = batch - int(body.older_than_hours * 3600) if body.older_than_hours else None
    with db.transaction() as conn:
        marked = articles_repo.mark_scope_read(
            conn, user.id, Scope(body.scope, body.id), batch=batch, published_before=published_before, max_id=body.max_id
        )
    return MarkedOut(marked=marked, batch=batch)


@router.post("/mark-read/undo", response_model=RestoredOut)
def undo_mark_scope_read(body: UndoMarkIn, user: UserDep, db: DatabaseDep) -> RestoredOut:
    with db.transaction() as conn:
        restored = articles_repo.undo_mark_scope_read(conn, user.id, Scope(body.scope, body.id), batch=body.batch)
    return RestoredOut(restored=restored)
