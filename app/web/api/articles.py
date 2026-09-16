from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.clock import now
from app.db.models import Scope, ScopeKind, SortOrder
from app.db.repositories import articles as articles_repo
from app.web.deps import DatabaseDep, UserDep
from app.web.schemas import (
    ArticleIdsIn,
    ArticleIdsOut,
    ArticleOut,
    ArticlePageOut,
    CountOut,
    MarkArticlesIn,
    StarArticlesIn,
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
ArticleState = Literal["unread", "starred", "all"]


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
    q: str | None = None,
) -> ArticlePageOut:
    """`q` searches the articles' full text (title and content)."""
    with db.transaction() as conn:
        page = articles_repo.page(
            conn, user.id, Scope(scope, scope_id),
            unread_only=unread_only, order=order, cursor=cursor, max_id=max_id, limit=limit, query=q or None,
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


# Sync primitives: a client fetches the ids it should have, works out what it's missing, and asks for those.
# Cheaper and more exact than paging a list that changes while you read it.


@router.get("/articles/ids", response_model=ArticleIdsOut)
def list_article_ids(
    user: UserDep,
    db: DatabaseDep,
    scope: ScopeKind = "all",
    scope_id: ScopeId = None,
    state: ArticleState = "unread",
    since_id: int | None = None,
    limit: int = articles_repo.MAX_IDS,
) -> ArticleIdsOut:
    """The ids of a scope's articles by state. `since_id` limits it to what arrived after a previous sync."""
    with db.transaction() as conn:
        ids = articles_repo.state_ids(
            conn, user.id, Scope(scope, scope_id), state=state, since_id=since_id, limit=limit
        )
        newest = articles_repo.max_id(conn, user.id, Scope(scope, scope_id))
    return ArticleIdsOut(ids=ids, max_id=newest)


@router.post("/articles/contents", response_model=list[ArticleOut])
def article_contents(body: ArticleIdsIn, user: UserDep, db: DatabaseDep) -> list[ArticleOut]:
    """The articles behind a list of ids, with their content. Ids you don't own are simply left out."""
    with db.transaction() as conn:
        return [to_schema(ArticleOut, article) for article in articles_repo.by_ids(conn, user.id, body.ids)]


@router.post("/articles/star", response_model=UpdatedOut)
def star_articles(body: StarArticlesIn, user: UserDep, db: DatabaseDep) -> UpdatedOut:
    """Stars or unstars a batch, for a client sending up what it queued while offline."""
    with db.transaction() as conn:
        updated = articles_repo.set_starred_many(conn, user.id, body.ids, starred=body.starred, now=now())
    return UpdatedOut(updated=updated)


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
