"""Organizing the stash: folders, smart lists (saved searches), and rules that sort new items."""

from fastapi import APIRouter

from app.clock import now
from app.db.repositories import smart_lists, stash_folders, stash_rules
from app.web.deps import DatabaseDep, UserDep
from app.web.schemas import (
    ChangedOut,
    FolderOrderOut,
    OkOut,
    ReorderIn,
    SmartListIn,
    SmartListOut,
    StashFolderIn,
    StashFolderOut,
    StashRuleIn,
    StashRuleOut,
    to_schema,
)

router = APIRouter(prefix="/api/stash")

# ------------------------------------------------------------------ folders


@router.get("/folders", response_model=list[StashFolderOut])
def list_folders(user: UserDep, db: DatabaseDep) -> list[StashFolderOut]:
    with db.transaction() as conn:
        return [to_schema(StashFolderOut, folder) for folder in stash_folders.list_for_user(conn, user.id)]


@router.post("/folders", status_code=201, response_model=StashFolderOut)
def create_folder(body: StashFolderIn, user: UserDep, db: DatabaseDep) -> StashFolderOut:
    with db.transaction() as conn:
        return to_schema(StashFolderOut, stash_folders.create(conn, user.id, body.name))


@router.post("/folders/reorder", response_model=FolderOrderOut)
def reorder_folders(body: ReorderIn, user: UserDep, db: DatabaseDep) -> FolderOrderOut:
    with db.transaction() as conn:
        return FolderOrderOut(ids=stash_folders.reorder(conn, user.id, body.ids))


@router.patch("/folders/{folder_id}", response_model=StashFolderOut)
def rename_folder(folder_id: int, body: StashFolderIn, user: UserDep, db: DatabaseDep) -> StashFolderOut:
    with db.transaction() as conn:
        return to_schema(StashFolderOut, stash_folders.rename(conn, user.id, folder_id, body.name))


@router.delete("/folders/{folder_id}", response_model=OkOut)
def delete_folder(folder_id: int, user: UserDep, db: DatabaseDep) -> OkOut:
    """Its items stay in the stash, in no folder."""
    with db.transaction() as conn:
        stash_folders.delete(conn, user.id, folder_id)
    return OkOut()


# ------------------------------------------------------------------ smart lists

_LIST_FIELDS = {"name": "name", "query": "query", "type": "type", "tag": "tag", "folderId": "folder_id"}


@router.get("/lists", response_model=list[SmartListOut])
def list_smart_lists(user: UserDep, db: DatabaseDep) -> list[SmartListOut]:
    with db.transaction() as conn:
        return [SmartListOut.from_list(smart_list) for smart_list in smart_lists.list_for_user(conn, user.id)]


@router.post("/lists", status_code=201, response_model=SmartListOut)
def create_smart_list(body: SmartListIn, user: UserDep, db: DatabaseDep) -> SmartListOut:
    with db.transaction() as conn:
        created = smart_lists.create(
            conn, user.id, name=body.name or "", query=body.query, type=body.type, tag=body.tag,
            folder_id=body.folderId,
        )
    return SmartListOut.from_list(created)


@router.patch("/lists/{list_id}", response_model=SmartListOut)
def update_smart_list(list_id: int, body: SmartListIn, user: UserDep, db: DatabaseDep) -> SmartListOut:
    changes = {_LIST_FIELDS[name]: getattr(body, name) for name in body.model_fields_set}
    with db.transaction() as conn:
        return SmartListOut.from_list(smart_lists.update(conn, user.id, list_id, **changes))


@router.delete("/lists/{list_id}", response_model=OkOut)
def delete_smart_list(list_id: int, user: UserDep, db: DatabaseDep) -> OkOut:
    with db.transaction() as conn:
        smart_lists.delete(conn, user.id, list_id)
    return OkOut()


# ------------------------------------------------------------------ rules


@router.get("/rules", response_model=list[StashRuleOut])
def list_rules(user: UserDep, db: DatabaseDep) -> list[StashRuleOut]:
    with db.transaction() as conn:
        return [StashRuleOut.from_rule(rule) for rule in stash_rules.list_for_user(conn, user.id)]


@router.post("/rules", status_code=201, response_model=StashRuleOut)
def create_rule(body: StashRuleIn, user: UserDep, db: DatabaseDep) -> StashRuleOut:
    with db.transaction() as conn:
        rule = stash_rules.create(
            conn, user.id, field=body.field, value=str(body.value), add_tag=body.addTag, folder_id=body.folderId,
            mark_reviewed=body.markReviewed, archive=body.archive, now=now(),
        )
    return StashRuleOut.from_rule(rule)


@router.post("/rules/apply", response_model=ChangedOut)
def apply_rules(user: UserDep, db: DatabaseDep) -> ChangedOut:
    """Runs the rules over everything saved that isn't archived."""
    with db.transaction() as conn:
        return ChangedOut(changed=stash_rules.apply_to_all(conn, user.id, now=now()))


@router.delete("/rules/{rule_id}", response_model=OkOut)
def delete_rule(rule_id: int, user: UserDep, db: DatabaseDep) -> OkOut:
    with db.transaction() as conn:
        stash_rules.delete(conn, user.id, rule_id)
    return OkOut()
