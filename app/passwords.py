"""Password hashing with scrypt from the standard library."""

import base64
import hashlib
import hmac
import secrets

from app.errors import InvalidInput

MIN_LENGTH = 8
MAX_LENGTH = 1024
_N, _R, _P, _KEY_BYTES = 2**15, 8, 1, 32
_MAX_MEMORY = 64 * 1024 * 1024


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES, maxmem=_MAX_MEMORY)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt, validate=True), n=int(n), r=int(r), p=int(p),
            dklen=len(expected), maxmem=_MAX_MEMORY,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def check_new_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise InvalidInput(f"Use at least {MIN_LENGTH} characters for the password")
    if len(password) > MAX_LENGTH:
        raise InvalidInput("That password is too long")
    return password


# Checked against when an email has no password account, so a wrong email takes as long as a wrong password.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
