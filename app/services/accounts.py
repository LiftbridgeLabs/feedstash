"""Accounts that sign in with a FeedStash password: first-run setup, checking passwords, and admin changes."""

import sqlite3

from app.db import Database
from app.db.models import User
from app.db.repositories import items as items_repo
from app.db.repositories import users as users_repo
from app.errors import Conflict, InvalidInput, NotFound
from app.images import ImageStore
from app.passwords import DUMMY_HASH, check_new_password, hash_password, verify_password

ALREADY_SET_UP = "FeedStash is already set up. Sign in instead."


def setup_first_account(db: Database, *, email: str, name: str | None, password: str) -> User:
    """Creates the first account, an admin. Fails once anyone exists."""
    password_hash = hash_password(check_new_password(password))
    with db.transaction() as conn:
        if users_repo.count(conn):
            raise Conflict(ALREADY_SET_UP)
        user = users_repo.create_local(conn, email=email, name=name, password_hash=password_hash, is_admin=True)
        if users_repo.count(conn) != 1:  # someone else finished setup at the same moment; roll this one back
            raise Conflict(ALREADY_SET_UP)
        return user


def authenticate(db: Database, email: str, password: str) -> User | None:
    """The account with this email and password, or None."""
    with db.transaction() as conn:
        found = users_repo.credentials(conn, email)
    if found is None:
        verify_password(password, DUMMY_HASH)
        return None
    user_id, stored = found
    if not verify_password(password, stored):
        return None
    with db.transaction() as conn:
        return users_repo.get(conn, user_id)


def change_own_password(db: Database, user: User, *, current_password: str, new_password: str) -> None:
    check_new_password(new_password)
    with db.transaction() as conn:
        stored = users_repo.get_password_hash(conn, user.id)
    if stored is None:
        raise InvalidInput("This account signs in with Google or single sign-on, so it has no password to change")
    if not verify_password(current_password, stored):
        raise InvalidInput("Your current password isn't right")
    new_hash = hash_password(new_password)
    with db.transaction() as conn:
        users_repo.set_password(conn, user.id, new_hash)


def create_account(db: Database, *, email: str, name: str | None, password: str, is_admin: bool) -> User:
    password_hash = hash_password(check_new_password(password))
    with db.transaction() as conn:
        return users_repo.create_local(conn, email=email, name=name, password_hash=password_hash, is_admin=is_admin)


def reset_password(db: Database, user_id: int, password: str) -> User:
    password_hash = hash_password(check_new_password(password))
    with db.transaction() as conn:
        users_repo.set_password(conn, user_id, password_hash)
        return users_repo.get(conn, user_id)


def set_admin(db: Database, user_id: int, is_admin: bool) -> User:
    with db.transaction() as conn:
        user = _existing(conn, user_id)
        if user.is_admin and not is_admin and users_repo.admin_count(conn) == 1:
            raise InvalidInput("FeedStash needs at least one admin")
        users_repo.set_admin(conn, user_id, is_admin)
        return users_repo.get(conn, user_id)


def delete_account(db: Database, images: ImageStore, *, acting_user_id: int, user_id: int) -> None:
    """Removes an account with everything it follows and saved, including its images."""
    if user_id == acting_user_id:
        raise InvalidInput("You can't remove your own account")
    with db.transaction() as conn:
        _existing(conn, user_id)
        image_names = items_repo.image_names_for_user(conn, user_id)
        users_repo.delete(conn, user_id)
    for name in image_names:
        images.delete(name)


def _existing(conn: sqlite3.Connection, user_id: int) -> User:
    user = users_repo.get(conn, user_id)
    if user is None:
        raise NotFound("No such account")
    return user
