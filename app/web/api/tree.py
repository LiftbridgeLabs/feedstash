from dataclasses import asdict

from fastapi import APIRouter

from app.db.repositories import articles as articles_repo
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import folders as folders_repo
from app.services import outgoing_email
from app.web.deps import DatabaseDep, SecretsDep, SettingsDep, StorageDep, UserDep
from app.web.schemas import ServerInfoOut, TreeOut, UserOut, to_schema

router = APIRouter(prefix="/api")


@router.get("/me", response_model=UserOut)
def me(user: UserDep) -> UserOut:
    return to_schema(UserOut, user)


@router.get("/server", response_model=ServerInfoOut)
def server_info(
    user: UserDep, db: DatabaseDep, settings: SettingsDep, secrets: SecretsDep, storage: StorageDep,
) -> ServerInfoOut:
    """What this server allows, for the app to show: whether it's managed, its limits and how much storage is used."""
    return ServerInfoOut(
        managed=settings.managed, account_limit=settings.account_limit,
        can_email=outgoing_email.configured(db, settings, secrets),
        storage_used=storage.used(), storage_limit=storage.limit_bytes,
    )


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
            page_capture=settings.page_capture,
        )
