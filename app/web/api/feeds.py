from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.db.models import Scope
from app.clock import now
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import muted_words
from app.feeds import discover, ingest, mute
from app.services import muting, subscriptions
from app.web.deps import DatabaseDep, SettingsDep, UserDep
from app.web.schemas import (
    DiscoverFeedOut,
    DiscoverOut,
    DiscoverPackOut,
    FeedOrderOut,
    FeedOut,
    FeedStatsOut,
    FeedReorderIn,
    FeedUpdateIn,
    FollowIn,
    MutedWordAddedOut,
    MutedWordIn,
    MutedWordOut,
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
async def update_feed(feed_id: int, body: FeedUpdateIn, user: UserDep, db: DatabaseDep, settings: SettingsDep) -> FeedOut:
    if body.url is not None:
        await subscriptions.change_url(db, settings, user.id, feed_id, body.url)

    def apply_rest():
        with db.transaction() as conn:
            if "title" in body.model_fields_set and body.title is not None:
                feeds_repo.rename(conn, user.id, feed_id, body.title)
            if "folder_id" in body.model_fields_set:
                feeds_repo.move(conn, user.id, feed_id, body.folder_id)
            if body.auto_stash is not None:
                feeds_repo.set_auto_stash(conn, user.id, feed_id, body.auto_stash)
            if body.full_text is not None:
                feeds_repo.set_full_text(conn, user.id, feed_id, body.full_text)
            if body.open_website is not None:
                feeds_repo.set_open_website(conn, user.id, feed_id, body.open_website)
            return to_schema(FeedOut, feeds_repo.get(conn, user.id, feed_id))

    return await run_in_threadpool(apply_rest)


@router.get("/discover", response_model=DiscoverOut)
def discover_feeds(user: UserDep, db: DatabaseDep) -> DiscoverOut:
    """Starter packs of feeds to follow, each feed marked if you already follow it. Follow with POST /api/feeds."""
    with db.transaction() as conn:
        return DiscoverOut(packs=[
            DiscoverPackOut(id=pack.id, name=pack.name, description=pack.description, feeds=[
                DiscoverFeedOut(title=feed.title, url=feed.url, site=feed.site, about=feed.about, cadence=feed.cadence,
                                followed=feeds_repo.is_followed(conn, user.id, feed.url))
                for feed in pack.feeds
            ])
            for pack in discover.packs()
        ])


@router.get("/feeds/{feed_id}/stats", response_model=FeedStatsOut)
def feed_stats(feed_id: int, user: UserDep, db: DatabaseDep) -> FeedStatsOut:
    """How much a feed posted lately, and how much of it was read, starred or saved: for pruning feeds."""
    with db.transaction() as conn:
        stats = feeds_repo.stats(conn, user.id, feed_id, now=now(), read_retention_days=user.read_retention_days)
    return FeedStatsOut(
        window_days=stats.window_days, posted=stats.posted, posts_per_week=round(stats.posted * 7 / stats.window_days, 1),
        read=stats.read, starred=stats.starred, saved=stats.saved,
    )


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


# ------------------------------------------------------------------ muted words


@router.get("/muted-words", response_model=list[MutedWordOut])
def list_muted_words(user: UserDep, db: DatabaseDep) -> list[MutedWordOut]:
    with db.transaction() as conn:
        return [to_schema(MutedWordOut, word) for word in muted_words.list_for_user(conn, user.id)]


@router.post("/muted-words", status_code=201, response_model=MutedWordAddedOut)
def mute_word(body: MutedWordIn, user: UserDep, db: DatabaseDep) -> MutedWordAddedOut:
    """New articles holding the word arrive already read; with `mark_unread_read`, unread ones holding it are marked
    read now too, undoable with the mark-read undo."""
    batch = now()
    with db.transaction() as conn:
        word = muted_words.create(
            conn, user.id, phrase=mute.clean(body.phrase), title_only=body.title_only, folder_id=body.folder_id,
            feed_id=body.feed_id, now=batch,
        )
        marked = muting.mark_unread_read(conn, user.id, word, batch=batch) if body.mark_unread_read else 0
    return MutedWordAddedOut(word=to_schema(MutedWordOut, word), marked=marked, batch=batch)


@router.delete("/muted-words/{word_id}", response_model=OkOut)
def unmute_word(word_id: int, user: UserDep, db: DatabaseDep) -> OkOut:
    with db.transaction() as conn:
        muted_words.delete(conn, user.id, word_id)
    return OkOut()
