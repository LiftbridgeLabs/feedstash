"""The Google Reader API, so reader apps that speak it — NetNewsWire, Reeder Classic, lire, and Android apps like
Capy Reader — can read and manage your FeedStash feeds.

Only the feeds half of FeedStash is here: the protocol has no idea what a stash is.

It's mounted twice, at the server root and under /api/greader.php, because clients disagree about whether they add
that path themselves (see main.py).

Signing in: ClientLogin with your email as the username and an API token (Settings → Connected apps) as the
password, so each app gets its own credential you can revoke. The token comes back as the Auth value and every
other call carries it as `Authorization: GoogleLogin auth=<token>`.
"""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MultiDict

from app import greader
from app.clock import now
from app.db.models import Feed, Scope, User
from app.db.repositories import articles as articles_repo
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import folders as folders_repo
from app.errors import InvalidInput, NotFound, ReaderError
from app.services import subscriptions
from app.web.auth import token_user
from app.web.deps import DatabaseDep, SettingsDep

router = APIRouter(include_in_schema=False)

API = "/reader/api/0"
DEFAULT_COUNT = 20
STATE_BATCH = 1000  # ids per write, well under SQLite's variable limit


def reader_user(request: Request) -> User:
    token = greader.auth_token(request.headers.get("authorization", ""))
    user = token_user(request, token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


ReaderUser = Annotated[User, Depends(reader_user)]


def ok() -> PlainTextResponse:
    """A fresh response each time: middleware adds headers to every response, so one shared instance would be
    mutated by concurrent requests."""
    return PlainTextResponse("OK")


async def _params(request: Request) -> MultiDict:
    """Clients send parameters in the query string or as a form, and repeat keys (i=, a=, s=) for lists."""
    items = list(request.query_params.multi_items())
    if request.method == "POST":
        form = await request.form()
        items += [(key, value) for key, value in form.multi_items() if isinstance(value, str)]
    return MultiDict(items)


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _item_ids(params: MultiDict) -> list[int]:
    ids = [greader.parse_item_id(value) for value in params.getlist("i")]
    return [article_id for article_id in ids if article_id is not None][: articles_repo.MAX_IDS]


def _find_feed(conn, user_id: int, value: str) -> Feed | None:
    """A feed by the id we gave out (feed/12) or by its address (feed/https://…), which some clients send."""
    feeds = feeds_repo.list_for_user(conn, user_id)
    if value.isdigit():
        return next((feed for feed in feeds if feed.id == int(value)), None)
    return next((feed for feed in feeds if feed.url == value), None)


def _scope(conn, user_id: int, stream: str) -> Scope | None:
    """The part of FeedStash a stream means, or None for one that doesn't exist (nothing to show, nothing to do)."""
    kind, value = greader.parse_stream(stream)
    if kind in ("reading-list", "read"):
        return Scope("all")
    if kind == "starred":
        return Scope("starred")
    if kind == "label":
        folder = folders_repo.find_by_name(conn, user_id, value)
        return Scope("folder", folder.id) if folder else None
    if kind == "feed":
        feed = _find_feed(conn, user_id, value)
        return Scope("feed", feed.id) if feed else None
    return None


def _stream_refs(conn, user_id: int, params: MultiDict, stream: str | None, *, ceiling: int):
    stream = greader.normalize_stream(stream or params.get("s") or greader.READING_LIST)
    scope = _scope(conn, user_id, stream)
    if scope is None:
        return [], None
    include = {greader.normalize_stream(tag) for tag in params.getlist("it")}
    exclude = {greader.normalize_stream(tag) for tag in params.getlist("xt")}
    read = True if greader.parse_stream(stream)[0] == "read" or greader.READ in include else (
        False if greader.READ in exclude else None)
    starred = True if greader.STARRED in include else (False if greader.STARRED in exclude else None)
    count = _int(params.get("n")) or DEFAULT_COUNT
    return articles_repo.stream_page(
        conn, user_id, scope, read=read, starred=starred,
        newer_than=_int(params.get("ot")), older_than=_int(params.get("nt")),
        oldest_first=params.get("r") == "o", limit=max(1, min(count, ceiling)), cursor=params.get("c") or None,
    )


def _items(conn, user_id: int, ids: list[int]) -> list[dict]:
    """The articles behind ids, in the order they were asked for."""
    articles = {article.id: article for article in articles_repo.by_ids(conn, user_id, ids)}
    feeds = {feed.id: feed for feed in feeds_repo.list_for_user(conn, user_id)}
    folder_names = {folder.id: folder.name for folder in folders_repo.list_for_user(conn, user_id)}
    return [
        greader.item(articles[article_id], feeds.get(articles[article_id].feed_id), folder_names)
        for article_id in ids if article_id in articles
    ]


# ------------------------------------------------------------------ signing in


@router.api_route("/accounts/ClientLogin", methods=["GET", "POST"])
async def client_login(request: Request) -> PlainTextResponse:
    params = await _params(request)
    email = (params.get("Email") or "").strip().lower()
    secret = (params.get("Passwd") or "").strip()
    user = await run_in_threadpool(token_user, request, secret) if email and secret else None
    if user is None or user.email.lower() != email:
        return PlainTextResponse("Error=BadAuthentication\n", status_code=403)
    return PlainTextResponse(f"SID={secret}\nLSID=null\nAuth={secret}\n")


@router.get(f"{API}/token")
def write_token(user: ReaderUser) -> PlainTextResponse:
    # Clients fetch this and send it back as T= on every write. It guards against cross-site requests riding on a
    # session cookie; ours are authenticated by a header a browser never sends on its own, so it's issued (clients
    # won't proceed without one) but there's nothing for it to check.
    return PlainTextResponse(hashlib.sha256(f"feedstash-reader:{user.id}".encode()).hexdigest()[:57])


@router.get(f"{API}/user-info")
def user_info(user: ReaderUser) -> dict:
    return {
        "userId": str(user.id), "userName": user.name or user.email, "userProfileId": str(user.id),
        "userEmail": user.email,
    }


# ------------------------------------------------------------------ feeds and folders


@router.get(f"{API}/subscription/list")
def subscription_list(user: ReaderUser, db: DatabaseDep) -> dict:
    with db.transaction() as conn:
        folder_names = {folder.id: folder.name for folder in folders_repo.list_for_user(conn, user.id)}
        feeds = feeds_repo.list_for_user(conn, user.id)
    return {"subscriptions": [
        {
            "id": greader.feed_stream(feed.id),
            "title": feed.title,
            "categories": [
                {"id": greader.label_stream(folder_names[feed.folder_id]), "label": folder_names[feed.folder_id]}
            ] if feed.folder_id in folder_names else [],
            "url": feed.url,
            "htmlUrl": feed.site_url or "",
            "iconUrl": "",
        }
        for feed in feeds
    ]}


@router.get(f"{API}/tag/list")
def tag_list(user: ReaderUser, db: DatabaseDep) -> dict:
    with db.transaction() as conn:
        folders = folders_repo.list_for_user(conn, user.id)
    return {"tags": [
        {"id": greader.STARRED},
        *({"id": greader.label_stream(folder.name), "type": "folder"} for folder in folders),
    ]}


@router.get(f"{API}/unread-count")
def unread_count(user: ReaderUser, db: DatabaseDep) -> dict:
    with db.transaction() as conn:
        feeds = feeds_repo.list_for_user(conn, user.id)
        folders = folders_repo.list_for_user(conn, user.id)
        newest = articles_repo.newest_unread_by_feed(conn, user.id)

    def entry(stream: str, count: int, published: int) -> dict:
        return {"id": stream, "count": count, "newestItemTimestampUsec": str(published * 1_000_000)}

    counts = [entry(greader.feed_stream(feed.id), feed.unread, newest.get(feed.id, 0)) for feed in feeds]
    for folder in folders:
        inside = [feed for feed in feeds if feed.folder_id == folder.id]
        counts.append(entry(
            greader.label_stream(folder.name), sum(feed.unread for feed in inside),
            max((newest.get(feed.id, 0) for feed in inside), default=0),
        ))
    total = sum(feed.unread for feed in feeds)
    counts.append(entry(greader.READING_LIST, total, max(newest.values(), default=0)))
    return {"max": total, "unreadcounts": counts}


@router.post(f"{API}/subscription/quickadd")
async def quickadd(request: Request, user: ReaderUser, db: DatabaseDep, settings: SettingsDep) -> dict:
    params = await _params(request)
    url = (params.get("quickadd") or "").strip().removeprefix("feed/")
    try:
        feed = await subscriptions.follow(db, settings, user.id, url=url)
    except ReaderError as exc:
        return {"numResults": 0, "query": url, "error": str(exc)}
    return {"numResults": 1, "query": url, "streamId": greader.feed_stream(feed.id), "streamName": feed.title}


@router.post(f"{API}/subscription/edit")
async def edit_subscription(request: Request, user: ReaderUser, db: DatabaseDep, settings: SettingsDep):
    params = await _params(request)
    action = params.get("ac")
    if action not in ("subscribe", "unsubscribe", "edit"):
        raise InvalidInput('ac must be "subscribe", "unsubscribe" or "edit"')
    title = (params.get("t") or "").strip() or None
    add_label = greader.label_name(params.get("a"))
    remove_label = greader.label_name(params.get("r"))

    for stream in params.getlist("s"):
        value = stream.strip().removeprefix("feed/")
        if action == "subscribe":
            await subscriptions.follow(db, settings, user.id, url=value, folder_name=add_label, title=title)
            continue

        def change(value: str = value) -> None:
            with db.transaction() as conn:
                feed = _find_feed(conn, user.id, value)
                if feed is None:
                    raise NotFound("Feed not found")
                if action == "unsubscribe":
                    feeds_repo.delete(conn, user.id, feed.id)
                    return
                if title:
                    feeds_repo.rename(conn, user.id, feed.id, title)
                if add_label:
                    feeds_repo.move(conn, user.id, feed.id, folders_repo.get_or_create(conn, user.id, add_label).id)
                elif remove_label:
                    feeds_repo.move(conn, user.id, feed.id, None)

        await run_in_threadpool(change)
    return ok()


@router.post(f"{API}/rename-tag")
async def rename_tag(request: Request, user: ReaderUser, db: DatabaseDep):
    params = await _params(request)
    old = greader.label_name(params.get("s") or params.get("t"))
    new = greader.label_name(params.get("dest"))
    if not old or not new:
        raise InvalidInput("Give the folder and its new name as label streams")

    def rename() -> None:
        with db.transaction() as conn:
            folder = folders_repo.find_by_name(conn, user.id, old)
            if folder is None:
                raise NotFound("Folder not found")
            folders_repo.rename(conn, user.id, folder.id, new)

    await run_in_threadpool(rename)
    return ok()


@router.post(f"{API}/disable-tag")
async def disable_tag(request: Request, user: ReaderUser, db: DatabaseDep):
    """Removes a folder. Its feeds stay, uncategorized — the same as deleting a folder in FeedStash."""
    params = await _params(request)
    name = greader.label_name(params.get("s") or params.get("t"))

    def remove() -> None:
        with db.transaction() as conn:
            folder = folders_repo.find_by_name(conn, user.id, name) if name else None
            if folder is None:
                raise NotFound("Folder not found")
            folders_repo.delete(conn, user.id, folder.id, unfollow_feeds=False)

    await run_in_threadpool(remove)
    return ok()


# ------------------------------------------------------------------ articles and their state


@router.api_route(f"{API}/stream/items/ids", methods=["GET", "POST"])
async def stream_item_ids(request: Request, user: ReaderUser, db: DatabaseDep) -> dict:
    params = await _params(request)

    def load():
        with db.transaction() as conn:
            return _stream_refs(conn, user.id, params, None, ceiling=articles_repo.MAX_IDS)

    refs, continuation = await run_in_threadpool(load)
    body = {"itemRefs": [
        {"id": str(article_id), "directStreamIds": [], "timestampUsec": str(published * 1_000_000)}
        for article_id, published in refs
    ]}
    if continuation:
        body["continuation"] = continuation
    return body


@router.api_route(f"{API}/stream/items/contents", methods=["GET", "POST"])
async def stream_item_contents(request: Request, user: ReaderUser, db: DatabaseDep) -> dict:
    params = await _params(request)
    ids = _item_ids(params)[: articles_repo.MAX_CONTENTS]

    def load():
        with db.transaction() as conn:
            return _items(conn, user.id, ids)

    return {"id": greader.READING_LIST, "updated": now(), "items": await run_in_threadpool(load)}


@router.get(f"{API}/stream/contents/{{stream:path}}")
@router.get(f"{API}/stream/contents")
async def stream_contents(request: Request, user: ReaderUser, db: DatabaseDep, stream: str = "") -> dict:
    """A stream's articles in one call. Some clients use this instead of fetching ids and then contents."""
    params = await _params(request)
    stream = greader.normalize_stream(stream or params.get("s") or greader.READING_LIST)

    def load():
        with db.transaction() as conn:
            refs, continuation = _stream_refs(conn, user.id, params, stream, ceiling=articles_repo.MAX_CONTENTS)
            return _items(conn, user.id, [article_id for article_id, _ in refs]), continuation

    items, continuation = await run_in_threadpool(load)
    body = {"id": stream, "updated": now(), "items": items}
    if continuation:
        body["continuation"] = continuation
    return body


@router.post(f"{API}/edit-tag")
async def edit_tag(request: Request, user: ReaderUser, db: DatabaseDep):
    """Marks read or unread, starred or not. Other tags (labels on single articles) have no FeedStash meaning and
    are accepted and ignored, so a client doesn't treat them as failures."""
    params = await _params(request)
    ids = _item_ids(params)
    adds = {greader.normalize_stream(tag) for tag in params.getlist("a")}
    removes = {greader.normalize_stream(tag) for tag in params.getlist("r")}

    def apply() -> None:
        with db.transaction() as conn:
            stamp = now()
            for start in range(0, len(ids), STATE_BATCH):
                batch = ids[start:start + STATE_BATCH]
                if greader.READ in adds:
                    articles_repo.set_read(conn, user.id, batch, read=True, now=stamp)
                if greader.READ in removes:
                    articles_repo.set_read(conn, user.id, batch, read=False, now=stamp)
                if greader.STARRED in adds:
                    articles_repo.set_starred_many(conn, user.id, batch, starred=True, now=stamp)
                if greader.STARRED in removes:
                    articles_repo.set_starred_many(conn, user.id, batch, starred=False, now=stamp)

    await run_in_threadpool(apply)
    return ok()


@router.post(f"{API}/mark-all-as-read")
async def mark_all_as_read(request: Request, user: ReaderUser, db: DatabaseDep):
    """Marks a stream read. `ts` (microseconds) spares anything newer, so articles that arrived after the client
    last looked aren't marked read unseen."""
    params = await _params(request)
    stream = greader.normalize_stream(params.get("s") or greader.READING_LIST)
    ts = _int(params.get("ts"))
    published_before = ts // 1_000_000 + 1 if ts else None

    def mark() -> None:
        with db.transaction() as conn:
            scope = _scope(conn, user.id, stream)
            if scope is not None:
                articles_repo.mark_scope_read(conn, user.id, scope, batch=now(), published_before=published_before)

    await run_in_threadpool(mark)
    return ok()
