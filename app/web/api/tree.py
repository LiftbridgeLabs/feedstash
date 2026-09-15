from dataclasses import asdict

from fastapi import APIRouter

from app.db.repositories import articles as articles_repo
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import folders as folders_repo
from app.web.deps import DatabaseDep, SettingsDep, UserDep
from app.web.schemas import TreeOut, UserOut, to_schema

router = APIRouter(prefix="/api")


@router.get("/me", response_model=UserOut)
def me(user: UserDep) -> UserOut:
    return to_schema(UserOut, user)


@router.get("/tree", response_model=TreeOut)
def tree(user: UserDep, db: DatabaseDep, settings: SettingsDep) -> TreeOut:
    """Everything the sidebar needs: folders, feeds with unread counts, and the Read later count."""
    with db.transaction() as conn:
        return TreeOut(
            folders=[asdict(folder) for folder in folders_repo.list_for_user(conn, user.id)],
            feeds=[asdict(feed) for feed in feeds_repo.list_for_user(conn, user.id)],
            starred_count=articles_repo.starred_count(conn, user.id),
            refresh_interval_minutes=settings.refresh_interval_minutes,
            version=settings.feedstash_version,
        )
