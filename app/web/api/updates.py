"""For admins: what changed since the release they last saw, and whether a newer one is out."""

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import changelog
from app.db import Database
from app.db.models import User
from app.db.repositories import users as users_repo
from app.services.updates import RELEASES_URL, is_newer
from app.web.deps import DatabaseDep, SettingsDep, UserDep
from app.web.schemas import OkOut, UpdatesOut

router = APIRouter(prefix="/api/admin/updates")


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins see release notes and updates")


def _seen_version(db: Database, user_id: int) -> str | None:
    with db.transaction() as conn:
        return users_repo.seen_version(conn, user_id)


@router.get("", response_model=UpdatesOut)
async def updates(request: Request, user: UserDep, db: DatabaseDep, settings: SettingsDep) -> UpdatesOut:
    _require_admin(user)
    current = settings.feedstash_version
    seen = await run_in_threadpool(_seen_version, db, user.id)
    latest = await request.app.state.update_checker.latest()
    available = latest is not None and is_newer(latest.version, current)
    return UpdatesOut(
        current=current,
        latest=latest.version if available else None,
        latest_url=latest.url if available else None,
        releases_url=RELEASES_URL,
        unseen=[
            {
                "version": release.version,
                "url": f"{RELEASES_URL}/tag/v{release.version}",
                "sections": [{"title": s.title, "items": s.items} for s in changelog.after_update(release)],
            }
            for release in changelog.unseen(changelog.releases(), current=current, seen=seen)
        ],
    )


@router.post("/seen", response_model=OkOut)
def mark_seen(user: UserDep, db: DatabaseDep, settings: SettingsDep) -> OkOut:
    """The admin has read the notes up to the running release."""
    _require_admin(user)
    if changelog.version_key(settings.feedstash_version):
        with db.transaction() as conn:
            users_repo.set_seen_version(conn, user.id, settings.feedstash_version)
    return OkOut()
