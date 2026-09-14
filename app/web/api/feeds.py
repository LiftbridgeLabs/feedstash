from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.db.models import Scope
from app.db.repositories import feeds as feeds_repo
from app.feeds import ingest
from app.services import subscriptions
from app.web.deps import DatabaseDep, SettingsDep, UserDep
from app.web.schemas import (
    FeedOrderOut,
    FeedOut,
    FeedReorderIn,
    FeedUpdateIn,
    FollowIn,
    OkOut,
    RefreshIn,
    RefreshOut,
    to_schema,
)

router = APIRouter(prefix="/api")


@router.post("/feeds", response_model=FeedOut)
async def follow_feed(body: FollowIn, user: UserDep, db: DatabaseDep, settings: SettingsDep) -> FeedOut:
    feed = await subscriptions.follow(
        db, settings, user.id, url=body.url, folder_id=body.folder_id, folder_name=body.folder_name, title=body.title
    )
    return to_schema(FeedOut, feed)


@router.post("/feeds/reorder", response_model=FeedOrderOut)
def reorder_feeds(body: FeedReorderIn, user: UserDep, db: DatabaseDep) -> FeedOrderOut:
    with db.transaction() as conn:
        ids = feeds_repo.reorder(conn, user.id, body.folder_id, body.ids)
    return FeedOrderOut(folder_id=body.folder_id, ids=ids)


@router.patch("/feeds/{feed_id}", response_model=FeedOut)
def update_feed(feed_id: int, body: FeedUpdateIn, user: UserDep, db: DatabaseDep) -> FeedOut:
    with db.transaction() as conn:
        if "title" in body.model_fields_set and body.title is not None:
            feeds_repo.rename(conn, user.id, feed_id, body.title)
        if "folder_id" in body.model_fields_set:
            feeds_repo.move(conn, user.id, feed_id, body.folder_id)
        return to_schema(FeedOut, feeds_repo.get(conn, user.id, feed_id))


@router.delete("/feeds/{feed_id}", response_model=OkOut)
def unfollow_feed(feed_id: int, user: UserDep, db: DatabaseDep) -> OkOut:
    with db.transaction() as conn:
        feeds_repo.delete(conn, user.id, feed_id)
    return OkOut()


@router.post("/refresh", response_model=RefreshOut)
async def refresh_now(body: RefreshIn, user: UserDep, db: DatabaseDep, settings: SettingsDep) -> RefreshOut:
    def feeds_in_scope():
        with db.transaction() as conn:
            return feeds_repo.fetch_states_in_scope(conn, user.id, Scope(body.scope, body.id))

    feeds = await run_in_threadpool(feeds_in_scope)
    added = await ingest.refresh(db, feeds, retention_days=settings.retention_days)
    return RefreshOut(feeds=len(feeds), new=added)
