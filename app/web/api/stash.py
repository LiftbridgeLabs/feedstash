"""The stash: things captured from anywhere (links, snippets, screenshots, emails).

/api/items, /api/tags and /uploads are also what the browser extension, email worker and phone apps in
clients/ use, so their shapes (camelCase fields, multi-link `links`) must stay stable.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.clock import iso, now
from app.db.models import ItemFilter
from app.db.repositories import items as items_repo
from app.db.repositories import pages as pages_repo
from app.db.repositories import smart_lists, stash_folders
from app.errors import Conflict, InvalidInput, NotFound
from app.images import MAX_IMAGE_BYTES
from app.services import stash
from app.web.deps import DatabaseDep, ImagesDep, SettingsDep, UserDep, api_client_name
from app.web.schemas import (
    OkOut,
    PageCopyOut,
    SmartListOut,
    StashArticleOut,
    StashFolderOut,
    StashItemOut,
    StashSummaryOut,
    TagCountOut,
    TagMergeIn,
    TagMergeOut,
    TagRenameIn,
    TagRenameOut,
    to_schema,
)

MAX_FIELD_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api")
uploads_router = APIRouter(include_in_schema=False)


async def _read_images(form) -> list[bytes]:
    """Every `image` part, in order. The whole request is capped (MAX_REQUEST_BYTES), so several large pictures go
    one per request to POST /api/items/{id}/images."""
    return [await upload.read(MAX_IMAGE_BYTES + 1) for upload in form.getlist("image") if isinstance(upload, UploadFile)]


async def _read_capture(request: Request) -> stash.Capture:
    """Items are posted as multipart/urlencoded forms (extension, phone apps, email worker) or as JSON."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        async with request.form(max_part_size=MAX_FIELD_BYTES, max_files=items_repo.MAX_IMAGES) as form:
            fields = {key: value for key, value in form.items() if isinstance(value, str)}
            images = await _read_images(form)
        return stash.Capture.from_fields(fields, images=images)
    try:
        fields = await request.json()
    except ValueError:
        raise InvalidInput("Send the item as JSON or as form data") from None
    if not isinstance(fields, dict):
        raise InvalidInput("Send the item as a JSON object")
    return stash.Capture.from_fields(fields)


@router.post("/items", status_code=201, response_model=StashItemOut)
async def create_item(request: Request, user: UserDep, db: DatabaseDep, images: ImagesDep) -> StashItemOut:
    capture = await _read_capture(request)
    item = await run_in_threadpool(
        stash.capture, db, images, user.id, capture, default_source=api_client_name(request) or "web"
    )
    return StashItemOut.from_item(item)


@router.get("/items", response_model=list[StashItemOut])
def list_items(
    user: UserDep,
    db: DatabaseDep,
    item_type: Annotated[str | None, Query(alias="type")] = None,
    tag: str | None = None,
    reviewed: bool | None = None,
    archived: bool = False,
    q: Annotated[str | None, Query(max_length=500)] = None,
    folder: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[StashItemOut]:
    criteria = ItemFilter(
        type=item_type or None, tag=tag or None, reviewed=reviewed, archived=archived, query=q or None,
        folder_id=folder, limit=limit, offset=offset,
    )
    with db.transaction() as conn:
        return [StashItemOut.from_item(item) for item in items_repo.search(conn, user.id, criteria)]


@router.get("/items/{item_id}", response_model=StashItemOut)
def get_item(item_id: int, user: UserDep, db: DatabaseDep) -> StashItemOut:
    with db.transaction() as conn:
        return StashItemOut.from_item(items_repo.get(conn, user.id, item_id))


@router.patch("/items/{item_id}", response_model=StashItemOut)
async def update_item(item_id: int, request: Request, user: UserDep, db: DatabaseDep, images: ImagesDep) -> StashItemOut:
    try:
        fields = await request.json()
    except ValueError:
        raise InvalidInput("Send the changes as a JSON object") from None
    if not isinstance(fields, dict):
        raise InvalidInput("Send the changes as a JSON object")
    item = await run_in_threadpool(stash.update, db, images, user.id, item_id, fields)
    return StashItemOut.from_item(item)


@router.post("/items/{item_id}/images", response_model=StashItemOut)
async def add_item_images(item_id: int, request: Request, user: UserDep, db: DatabaseDep, images: ImagesDep) -> StashItemOut:
    """Adds pictures (multipart `image` parts) after the item's others."""
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise InvalidInput("Send the pictures as multipart form data")
    async with request.form(max_part_size=MAX_FIELD_BYTES, max_files=items_repo.MAX_IMAGES) as form:
        data = await _read_images(form)
    item = await run_in_threadpool(stash.add_images, db, images, user.id, item_id, data)
    return StashItemOut.from_item(item)


@router.get("/items/{item_id}/page", response_model=PageCopyOut)
def get_saved_page(item_id: int, user: UserDep, db: DatabaseDep) -> PageCopyOut:
    """The readable copy saved of the item's web page."""
    with db.transaction() as conn:
        copy = pages_repo.get_copy(conn, user.id, item_id)
    return PageCopyOut(
        url=copy.url, status=copy.status, title=copy.title, html=copy.html,
        fetchedAt=iso(copy.fetched_at) if copy.fetched_at else None, error=copy.error,
    )


@router.post("/items/{item_id}/page/refresh", response_model=OkOut)
def refresh_saved_page(item_id: int, user: UserDep, db: DatabaseDep, settings: SettingsDep) -> OkOut:
    """Saves the item's web page again."""
    if not settings.page_capture:
        raise Conflict("This server doesn't save web pages (PAGE_CAPTURE is off)")
    with db.transaction() as conn:
        pages_repo.requeue(conn, user.id, item_id, now=now())
    return OkOut()


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, user: UserDep, db: DatabaseDep, images: ImagesDep) -> Response:
    stash.remove(db, images, user.id, item_id)
    return Response(status_code=204)


@router.get("/tags", response_model=list[TagCountOut])
def list_tags(user: UserDep, db: DatabaseDep) -> list[TagCountOut]:
    with db.transaction() as conn:
        return [TagCountOut(name=tag.name, count=tag.count) for tag in items_repo.tag_counts(conn, user.id)]


@router.post("/tags/rename", response_model=TagRenameOut)
def rename_tag(body: TagRenameIn, user: UserDep, db: DatabaseDep) -> TagRenameOut:
    """Renames a tag on every item, or merges it into another tag that already has the new name."""
    with db.transaction() as conn:
        name, items, merged = items_repo.rename_tag(conn, user.id, body.name, body.newName, now=now())
    return TagRenameOut(name=name, items=items, merged=merged)


@router.post("/tags/merge", response_model=TagMergeOut)
def merge_tags(body: TagMergeIn, user: UserDep, db: DatabaseDep) -> TagMergeOut:
    """Replaces several tags with one on every item, in one transaction; `into` can be one of them or a new name."""
    with db.transaction() as conn:
        name, items, merged = items_repo.merge_tags(conn, user.id, body.names, body.into, now=now())
    return TagMergeOut(name=name, items=items, merged=merged)


@router.get("/stash/summary", response_model=StashSummaryOut)
def stash_summary(user: UserDep, db: DatabaseDep) -> StashSummaryOut:
    """Counts, folders and smart lists for the sidebar."""
    with db.transaction() as conn:
        summary = items_repo.summary(conn, user.id)
        folders = stash_folders.list_for_user(conn, user.id)
        lists = smart_lists.list_for_user(conn, user.id)
    return StashSummaryOut(
        inbox=summary.inbox, total=summary.total, archived=summary.archived, by_type=summary.by_type,
        folders=[to_schema(StashFolderOut, folder) for folder in folders],
        lists=[SmartListOut.from_list(smart_list) for smart_list in lists],
    )


@router.post("/articles/{article_id}/stash", response_model=StashArticleOut)
def stash_article(article_id: int, user: UserDep, db: DatabaseDep) -> StashArticleOut:
    item, created = stash.stash_article(db, user.id, article_id)
    return StashArticleOut(item=StashItemOut.from_item(item), created=created)


@uploads_router.get("/uploads/{name}")
def serve_upload(name: str, images: ImagesDep) -> FileResponse:
    """Not behind sign-in: names are random, so an image URL works as its own key."""
    path = images.path(name)
    if path is None:
        raise NotFound("Not found")
    return FileResponse(
        path, media_type=images.media_type(name), headers={"Cache-Control": "private, max-age=31536000, immutable"}
    )
