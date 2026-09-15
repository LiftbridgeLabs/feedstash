"""Bulk import of saved links. The web app reads bookmark files in the browser and sends the chosen links here."""

from fastapi import APIRouter

from app.services import bookmarks
from app.web.deps import DatabaseDep, UserDep
from app.web.schemas import ImportLinksIn, ImportLinksOut

router = APIRouter(prefix="/api")


@router.post("/items/import", response_model=ImportLinksOut)
def import_links(body: ImportLinksIn, user: UserDep, db: DatabaseDep) -> ImportLinksOut:
    links = [bookmarks.ImportedLink(**link.model_dump()) for link in body.links]
    result = bookmarks.import_links(db, user.id, links)
    return ImportLinksOut(added=result.added, already_saved=result.already_saved, invalid=result.invalid)
