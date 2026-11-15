"""Proving a change with the account's password, where an API token alone isn't enough."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request

from app.db.models import User
from app.errors import ReaderError
from app.services.accounts import WrongPassword
from app.web.ratelimit import LoginLimiter


@asynccontextmanager
async def password_try(request: Request, user: User) -> AsyncIterator[None]:
    """Wraps a check of the account's password so that wrong ones count toward the same limit as failed sign-ins:
    a token can't be used to guess the password. The try is counted before it's checked, as sign-in does, and
    uncounted unless the body raises WrongPassword."""
    limiter: LoginLimiter = request.app.state.login_limiter
    address = request.client.host if request.client else "unknown"
    if wait := limiter.retry_after(address, user.email):
        minutes = max(1, round(wait / 60))
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong passwords. Try again in {minutes} minute{'' if minutes == 1 else 's'}.",
            headers={"Retry-After": str(wait)},
        )
    limiter.record_failure(address, user.email)
    try:
        yield
    except WrongPassword:
        raise
    except ReaderError:
        limiter.forgive(address, user.email)  # the password was right (or never asked for): not a guess
        raise
    limiter.forgive(address, user.email)
