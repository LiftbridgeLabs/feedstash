"""Your own password and preferences, and (for admins) everyone who can sign in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.db.models import User
from app.db.repositories import users as users_repo
from app.services import accounts
from app.web.auth import PASSWORD_CHECKS, start_session
from app.web.deps import DatabaseDep, ImagesDep, SessionUserDep, UserDep
from app.web.schemas import (
    AccountOut, AccountPrefsIn, AccountUpdateIn, NewAccountIn, OkOut, PasswordChangeIn, UserOut, to_schema,
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
    """Your own preferences: how long read articles are kept."""
    with db.transaction() as conn:
        users_repo.set_read_retention(conn, user.id, body.read_retention_days)
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
