"""Your own password, and (for admins) everyone who can sign in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.db.models import User
from app.db.repositories import users as users_repo
from app.services import accounts
from app.web.deps import DatabaseDep, ImagesDep, UserDep
from app.web.schemas import AccountOut, AccountUpdateIn, NewAccountIn, OkOut, PasswordChangeIn

router = APIRouter(prefix="/api")


def session_only_user(request: Request, user: UserDep) -> User:
    """Account changes need the web app: a leaked API token must not be enough to take over accounts."""
    if getattr(request.state, "api_token", None) is not None:
        raise HTTPException(status_code=403, detail="Manage accounts from the web app, not with an API token")
    return user


SessionUserDep = Annotated[User, Depends(session_only_user)]


def admin_user(user: SessionUserDep) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can manage accounts")
    return user


AdminDep = Annotated[User, Depends(admin_user)]


@router.post("/account/password", response_model=OkOut)
def change_password(body: PasswordChangeIn, user: SessionUserDep, db: DatabaseDep) -> OkOut:
    accounts.change_own_password(db, user, current_password=body.current_password, new_password=body.new_password)
    return OkOut()


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(admin: AdminDep, db: DatabaseDep) -> list[AccountOut]:
    with db.transaction() as conn:
        return [AccountOut.from_user(user) for user in users_repo.list_all(conn)]


@router.post("/accounts", status_code=201, response_model=AccountOut)
def create_account(body: NewAccountIn, admin: AdminDep, db: DatabaseDep) -> AccountOut:
    user = accounts.create_account(db, email=body.email, name=body.name, password=body.password, is_admin=body.is_admin)
    return AccountOut.from_user(user)


@router.patch("/accounts/{user_id}", response_model=AccountOut)
def update_account(user_id: int, body: AccountUpdateIn, admin: AdminDep, db: DatabaseDep) -> AccountOut:
    """Sets a new password and/or changes admin rights."""
    if body.password is not None:
        accounts.reset_password(db, user_id, body.password)
    if body.is_admin is not None:
        accounts.set_admin(db, user_id, body.is_admin)
    with db.transaction() as conn:
        user = users_repo.get(conn, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such account")
    return AccountOut.from_user(user)


@router.delete("/accounts/{user_id}", status_code=204)
def delete_account(user_id: int, admin: AdminDep, db: DatabaseDep, images: ImagesDep) -> Response:
    accounts.delete_account(db, images, acting_user_id=admin.id, user_id=user_id)
    return Response(status_code=204)
