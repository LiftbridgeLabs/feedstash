"""Two-step sign-in: a code from an authenticator app (or a one-time recovery code) after the password.

Only password sign-in asks for it: Google and single sign-on have their own, and API tokens are made while signed in.
Turning it on, off, or making new recovery codes asks for the account's password again.
"""

import secrets as random
from dataclasses import dataclass

from app import totp
from app.crypto import SecretBox
from app.db import Database
from app.db.models import User
from app.db.repositories import two_step as repo
from app.db.repositories import users as users_repo
from app.errors import Conflict, InvalidInput, NotFound
from app.passwords import verify_password

RECOVERY_CODES = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # nothing that reads two ways (l/1, o/0)


@dataclass(frozen=True, slots=True)
class Status:
    enabled: bool
    recovery_codes_left: int


def status(db: Database, user_id: int) -> Status:
    with db.transaction() as conn:
        return Status(repo.enabled(conn, user_id), repo.recovery_codes_left(conn, user_id))


def _check_password(db: Database, user: User, password: str) -> None:
    with db.transaction() as conn:
        stored = users_repo.get_password_hash(conn, user.id)
    if stored is None:
        raise InvalidInput("Two-step sign-in is for accounts that sign in with a password. Google and single "
                           "sign-on have their own.")
    if not verify_password(password or "", stored):
        raise InvalidInput("Your password isn't right")


def _recovery_code() -> str:
    letters = "".join(random.choice(_ALPHABET) for _ in range(10))
    return f"{letters[:5]}-{letters[5:]}"


def _normalize_recovery(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def begin(db: Database, secrets: SecretBox, user: User, *, password: str, now: int) -> tuple[str, str]:
    """A new secret for the authenticator app. Returns it and the otpauth:// link its QR code holds."""
    _check_password(db, user, password)
    secret = totp.new_secret()
    with db.transaction() as conn:
        if repo.enabled(conn, user.id):
            raise Conflict("Two-step sign-in is already on")
        repo.start(conn, user.id, secrets.encrypt(secret), now=now)
    return secret, totp.setup_uri(secret, account=user.email)


def confirm(db: Database, secrets: SecretBox, user: User, *, code: str, now: int) -> list[str]:
    """Turns it on once the app gives a right code. Returns the recovery codes, shown this once."""
    with db.transaction() as conn:
        found = repo.get(conn, user.id)
        if found is None:
            raise NotFound("Start setting up two-step sign-in first")
        if found.enabled:
            raise Conflict("Two-step sign-in is already on")
        secret = secrets.decrypt(found.secret)
        step = totp.matching_step(secret, code, now=now) if secret else None
        if step is None:
            raise InvalidInput("That code isn't right. Check the app shows FeedStash, and that your phone's clock "
                               "is set automatically.")
        repo.enable(conn, user.id, step=step, now=now)
        codes = [_recovery_code() for _ in range(RECOVERY_CODES)]
        repo.replace_recovery_codes(conn, user.id, [_normalize_recovery(c) for c in codes])
        users_repo.end_sessions(conn, user.id)  # every other browser signs in again, now with a code
    return codes


def verify(db: Database, secrets: SecretBox, user_id: int, code: str, *, now: int) -> bool:
    """A sign-in's second step: a code from the app (each works once) or an unused recovery code."""
    with db.transaction() as conn:
        found = repo.get(conn, user_id)
        if found is None or not found.enabled:
            return False
        secret = secrets.decrypt(found.secret)
        step = totp.matching_step(secret, code, now=now, after_step=found.last_step) if secret else None
        if step is not None:
            return repo.use_step(conn, user_id, step)
        recovery = _normalize_recovery(code)
        return len(recovery) == 10 and repo.use_recovery_code(conn, user_id, recovery, now=now)


def new_recovery_codes(db: Database, user: User, *, password: str) -> list[str]:
    _check_password(db, user, password)
    codes = [_recovery_code() for _ in range(RECOVERY_CODES)]
    with db.transaction() as conn:
        if not repo.enabled(conn, user.id):
            raise Conflict("Two-step sign-in isn't on")
        repo.replace_recovery_codes(conn, user.id, [_normalize_recovery(c) for c in codes])
    return codes


def turn_off(db: Database, user: User, *, password: str) -> None:
    _check_password(db, user, password)
    with db.transaction() as conn:
        repo.delete(conn, user.id)


def turn_off_for(db: Database, user_id: int) -> bool:
    """For an admin or the server's owner, when someone has lost their phone and their recovery codes. Their
    browsers are signed out too, in case someone else has the phone."""
    with db.transaction() as conn:
        if users_repo.get(conn, user_id) is None:
            raise NotFound("No such account")
        if not repo.delete(conn, user_id):
            return False
        users_repo.end_sessions(conn, user_id)
        return True
