"""Time-based one-time codes (RFC 6238, the 6-digit codes authenticator apps show), with the standard library only.

Codes change every 30 seconds; one step either side is accepted for a clock that's a little off. A code is good
once: the caller keeps the last step used and passes it back, so a code someone saw over a shoulder can't be
replayed.
"""

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # steps either side of now that still count


def new_secret() -> str:
    """160 random bits in base32, as authenticator apps expect (RFC 4226's recommended length)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    secret = secret.strip().replace(" ", "").upper()
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def step_of(timestamp: float) -> int:
    return int(timestamp // STEP_SECONDS)


def matching_step(secret: str, code: str, *, now: float, after_step: int = 0) -> int | None:
    """The step a typed code belongs to, if it's right for now (± WINDOW) and newer than `after_step`."""
    code = "".join(ch for ch in code if ch in "0123456789")  # other scripts' digits can't be compared, and aren't a code
    if len(code) != DIGITS:
        return None
    current = step_of(now)
    found = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), code) and step > after_step:
            found = step
    return found


def setup_uri(secret: str, *, account: str, issuer: str = "FeedStash") -> str:
    """What the QR code holds: otpauth://totp/Issuer:account?secret=…&issuer=…"""
    label = quote(f"{issuer}:{account}", safe="@:")
    return f"otpauth://totp/{label}?" + urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS})
