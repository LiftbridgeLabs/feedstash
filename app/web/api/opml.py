from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app import opml
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import folders as folders_repo
from app.errors import InvalidInput
from app.feeds import ingest
from app.services import subscriptions
from app.web.deps import DatabaseDep, SettingsDep, UserDep, run_in_background
from app.web.schemas import ImportOut

MAX_OPML_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api")


@router.post("/opml/import", response_model=ImportOut)
async def import_opml(
    request: Request, user: UserDep, db: DatabaseDep, settings: SettingsDep, file: UploadFile = File(...)
) -> ImportOut:
    data = await file.read(MAX_OPML_BYTES + 1)
    if len(data) > MAX_OPML_BYTES:
        raise InvalidInput("OPML file is too large")
    result = await run_in_threadpool(subscriptions.import_opml, db, user.id, data)
    # Fetch the new feeds after responding; the page polls the sidebar to show progress.
    run_in_background(request, ingest.refresh(db, result.pending, retention_days=settings.retention_days))
    return ImportOut(added=result.added, skipped=result.skipped, folders_created=result.folders_created)


@router.get("/opml/export")
def export_opml(user: UserDep, db: DatabaseDep) -> Response:
    with db.transaction() as conn:
        document = opml.build_opml(folders_repo.list_for_user(conn, user.id), feeds_repo.list_for_user(conn, user.id))
    return Response(
        document,
        media_type="text/x-opml",
        headers={"Content-Disposition": 'attachment; filename="reader-subscriptions.opml"'},
    )
