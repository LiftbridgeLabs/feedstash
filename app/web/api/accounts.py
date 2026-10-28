"""Your own password and preferences, and (for admins) everyone who can sign in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.db.models import User
from app.db.repositories import invites as invites_repo
from app.db.repositories import users as users_repo
from app.services import accounts
from app.web.auth import PASSWORD_CHECKS, start_session
from app.web.deps import DatabaseDep, ImagesDep, SessionUserDep, SettingsDep, UserDep
from app.web.schemas import (
    AccountOut, AccountPrefsIn, AccountUpdateIn, InviteIn, InviteOut, NewAccountIn, OkOut, PasswordChangeIn, UserOut,
    to_schema,
)

router = APIRouter(prefix="/api")


def admin_user(user: SessionUserDep) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can manage accounts")
    return user


AdminDep = Annotated[User, Depends(admin_user)]


@router.post("/account/password", response_model=OkOut)
async def change_password(body: PasswordChangeIn, request: Request, user: SessionUserDep, db: DatabaseDep) -> OkOut:
    """Changes your password. Every other browser signed in to the account is signed out; this one stays in."""
    async with PASSWORD_CHECKS:
        await run_in_threadpool(
            accounts.change_own_password, db, user,
            current_password=body.current_password, new_password=body.new_password,
        )
    await start_session(request, user.id)
    return OkOut()


@router.post("/account/sign-out-others", response_model=OkOut)
async def sign_out_other_browsers(request: Request, user: SessionUserDep, db: DatabaseDep) -> OkOut:
    """Signs out every other browser signed in to your account (API tokens are separate: revoke those one by one)."""

    def end() -> None:
        with db.transaction() as conn:
            users_repo.end_sessions(conn, user.id)

    await run_in_threadpool(end)
    await start_session(request, user.id)
    return OkOut()


@router.patch("/account", response_model=UserOut)
def update_preferences(body: AccountPrefsIn, user: SessionUserDep, db: DatabaseDep) -> UserOut:
    """Your own preferences, each only when sent: how long read articles are kept, and which halves of the app you
    use (the other is hidden, never deleted)."""
    with db.transaction() as conn:
        if body.read_retention_days is not None:
            users_repo.set_read_retention(conn, user.id, body.read_retention_days)
        if body.sections is not None:
            users_repo.set_sections(conn, user.id, body.sections)
        return to_schema(UserOut, users_repo.get(conn, user.id))


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(admin: AdminDep, db: DatabaseDep) -> list[AccountOut]:
    with db.transaction() as conn:
        return [AccountOut.from_user(user) for user in users_repo.list_all(conn)]


@router.post("/accounts", status_code=201, response_model=AccountOut)
def create_account(body: NewAccountIn, admin: AdminDep, db: DatabaseDep) -> AccountOut:
    user = accounts.create_account(db, email=body.email, name=body.name, password=body.password, is_admin=body.is_admin)
    return AccountOut.from_user(user)


@router.patch("/accounts/{user_id}", response_model=AccountOut)
async def update_account(
    user_id: int, body: AccountUpdateIn, request: Request, admin: AdminDep, db: DatabaseDep
) -> AccountOut:
    """Sets a new password (which signs that account out everywhere) and/or changes admin rights."""
    if body.password is not None:
        async with PASSWORD_CHECKS:
            await run_in_threadpool(accounts.reset_password, db, user_id, body.password)
        if user_id == admin.id:
            await start_session(request, admin.id)  # an admin resetting their own password stays signed in here
    if body.is_admin is not None:
        await run_in_threadpool(accounts.set_admin, db, user_id, body.is_admin)

    def load() -> User | None:
        with db.transaction() as conn:
            return users_repo.get(conn, user_id)

    user = await run_in_threadpool(load)
    if user is None:
        raise HTTPException(status_code=404, detail="No such account")
    return AccountOut.from_user(user)


@router.delete("/accounts/{user_id}", status_code=204)
def delete_account(user_id: int, admin: AdminDep, db: DatabaseDep, images: ImagesDep) -> Response:
    accounts.delete_account(db, images, acting_user_id=admin.id, user_id=user_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ invite links


@router.get("/invites", response_model=list[InviteOut])
def list_invites(admin: AdminDep, db: DatabaseDep) -> list[InviteOut]:
    """Invites not yet used or expired."""
    with db.transaction() as conn:
        return [to_schema(InviteOut, invite) for invite in invites_repo.pending(conn, now=now())]


@router.post("/invites", status_code=201, response_model=InviteOut)
def create_invite(body: InviteIn, admin: AdminDep, db: DatabaseDep, settings: SettingsDep) -> InviteOut:
    """A one-use link for one person to make an ordinary password account, at each of the server's addresses
    (https ones first: those are the ones that work from outside). The links are only in this reply."""
    if not settings.password_login:
        raise HTTPException(status_code=409, detail="Invites make password accounts, and password sign-in is turned off")
    with db.transaction() as conn:
        invite, token = invites_repo.create(conn, admin.id, email=body.email, days=body.days, now=now())
    servers = sorted(settings.base_urls, key=lambda url: not url.startswith("https://"))
    links = [f"{server.rstrip('/')}/invite#{token}" for server in servers]
    return InviteOut(**to_schema(InviteOut, invite).model_dump(exclude={"links"}), links=links)


@router.delete("/invites/{invite_id}", response_model=OkOut)
def cancel_invite(invite_id: int, admin: AdminDep, db: DatabaseDep) -> OkOut:
    with db.transaction() as conn:
        invites_repo.delete(conn, invite_id)
    return OkOut()
