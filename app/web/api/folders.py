from fastapi import APIRouter

from app.db.repositories import folders as folders_repo
from app.web.deps import DatabaseDep, UserDep
from app.web.schemas import FolderIn, FolderOrderOut, FolderOut, OkOut, ReorderIn, to_schema

router = APIRouter(prefix="/api")


@router.post("/folders", response_model=FolderOut)
def create_folder(body: FolderIn, user: UserDep, db: DatabaseDep) -> FolderOut:
    with db.transaction() as conn:
        return to_schema(FolderOut, folders_repo.create(conn, user.id, body.name))


@router.post("/folders/reorder", response_model=FolderOrderOut)
def reorder_folders(body: ReorderIn, user: UserDep, db: DatabaseDep) -> FolderOrderOut:
    with db.transaction() as conn:
        return FolderOrderOut(ids=folders_repo.reorder(conn, user.id, body.ids))


@router.patch("/folders/{folder_id}", response_model=FolderOut)
def rename_folder(folder_id: int, body: FolderIn, user: UserDep, db: DatabaseDep) -> FolderOut:
    with db.transaction() as conn:
        return to_schema(FolderOut, folders_repo.rename(conn, user.id, folder_id, body.name))


@router.delete("/folders/{folder_id}", response_model=OkOut)
def delete_folder(folder_id: int, user: UserDep, db: DatabaseDep, unfollow: bool = False) -> OkOut:
    with db.transaction() as conn:
        folders_repo.delete(conn, user.id, folder_id, unfollow_feeds=unfollow)
    return OkOut()
