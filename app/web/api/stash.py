"""The stash: things captured from anywhere (links, snippets, screenshots, emails).

/api/items, /api/tags and /uploads are also what the browser extension, email worker and phone apps in
clients/ use, so their shapes (camelCase fields, multi-link `links`) must stay stable.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.db.models import ItemFilter
from app.db.repositories import items as items_repo
from app.errors import InvalidInput, NotFound
from app.images import MAX_IMAGE_BYTES
from app.services import stash
from app.web.deps import DatabaseDep, ImagesDep, UserDep, api_client_name
from app.web.schemas import StashArticleOut, StashItemOut, StashSummaryOut, TagCountOut

MAX_FIELD_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api")
uploads_router = APIRouter(include_in_schema=False)


async def _read_capture(request: Request) -> stash.Capture:
    """Items are posted as multipart/urlencoded forms (extension, phone apps, email worker) or as JSON."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        async with request.form(max_part_size=MAX_FIELD_BYTES) as form:
            fields = {key: value for key, value in form.items() if isinstance(value, str)}
            upload = form.get("image")
            image = await upload.read(MAX_IMAGE_BYTES + 1) if isinstance(upload, UploadFile) else None
        return stash.Capture.from_fields(fields, image=image)
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
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[StashItemOut]:
    criteria = ItemFilter(
        type=item_type or None, tag=tag or None, reviewed=reviewed, archived=archived, query=q or None,
        limit=limit, offset=offset,
    )
    with db.transaction() as conn:
        return [StashItemOut.from_item(item) for item in items_repo.search(conn, user.id, criteria)]


@router.get("/items/{item_id}", response_model=StashItemOut)
def get_item(item_id: int, user: UserDep, db: DatabaseDep) -> StashItemOut:
    with db.transaction() as conn:
        return StashItemOut.from_item(items_repo.get(conn, user.id, item_id))


@router.patch("/items/{item_id}", response_model=StashItemOut)
async def update_item(item_id: int, request: Request, user: UserDep, db: DatabaseDep) -> StashItemOut:
    try:
        fields = await request.json()
    except ValueError:
        raise InvalidInput("Send the changes as a JSON object") from None
    if not isinstance(fields, dict):
        raise InvalidInput("Send the changes as a JSON object")
    item = await run_in_threadpool(stash.update, db, user.id, item_id, fields)
    return StashItemOut.from_item(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, user: UserDep, db: DatabaseDep, images: ImagesDep) -> Response:
    stash.remove(db, images, user.id, item_id)
    return Response(status_code=204)


@router.get("/tags", response_model=list[TagCountOut])
def list_tags(user: UserDep, db: DatabaseDep) -> list[TagCountOut]:
    with db.transaction() as conn:
        return [TagCountOut(name=tag.name, count=tag.count) for tag in items_repo.tag_counts(conn, user.id)]


@router.get("/stash/summary", response_model=StashSummaryOut)
def stash_summary(user: UserDep, db: DatabaseDep) -> StashSummaryOut:
    """Counts for the sidebar."""
    with db.transaction() as conn:
        summary = items_repo.summary(conn, user.id)
    return StashSummaryOut(inbox=summary.inbox, total=summary.total, archived=summary.archived, by_type=summary.by_type)


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
