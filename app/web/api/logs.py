"""For admins: the log's level and size, and reading or downloading it (Settings → Logs)."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.db.models import User
from app.db.repositories import app_settings as app_settings_repo
from app.errors import InvalidInput
from app.logs import LogSettings
from app.web.deps import DatabaseDep, SessionUserDep
from app.web.schemas import LogLinesOut, LogSettingsIn, LogSettingsOut

router = APIRouter(prefix="/api/admin/logs")


def _admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can see and change the logs")


def _out(request: Request, settings: LogSettings) -> LogSettingsOut:
    return LogSettingsOut(**asdict(settings), directory=str(request.app.state.log_files.directory))


@router.get("/settings", response_model=LogSettingsOut)
def get_settings(request: Request, user: SessionUserDep, db: DatabaseDep) -> LogSettingsOut:
    _admin(user)
    with db.transaction() as conn:
        saved = app_settings_repo.get_all(conn, "logs.")
    return _out(request, LogSettings.from_strings(saved, request.app.state.log_default))


@router.put("/settings", response_model=LogSettingsOut)
def put_settings(body: LogSettingsIn, request: Request, user: SessionUserDep, db: DatabaseDep) -> LogSettingsOut:
    _admin(user)
    try:
        settings = LogSettings(**body.model_dump()).checked()
    except ValueError as err:
        raise InvalidInput(str(err)) from None
    with db.transaction() as conn:
        app_settings_repo.set_many(conn, settings.as_strings())
    request.app.state.log_files.apply(settings)
    return _out(request, settings)


@router.get("", response_model=LogLinesOut)
async def recent_lines(request: Request, user: SessionUserDep, lines: int = 300) -> LogLinesOut:
    _admin(user)
    lines = max(1, min(lines, 2000))
    return LogLinesOut(lines=await run_in_threadpool(request.app.state.log_files.tail, lines))


@router.get("/download")
def download(request: Request, user: SessionUserDep) -> StreamingResponse:
    """Streamed: at the largest settings the log runs to a couple of gigabytes."""
    _admin(user)
    return StreamingResponse(
        request.app.state.log_files.stream(), media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="feedstash-log.txt"'},
    )
