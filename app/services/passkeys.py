"""Passkeys (WebAuthn): signing in with Face ID, Touch ID, Windows Hello, a phone or a security key.

A passkey proves the device and the person (the device checks their face, fingerprint or PIN), so it signs in on its
own: no password, and no two-step code. Browsers only allow passkeys on https addresses (and http://localhost), and
each passkey belongs to the address it was made on. A server reached at an https address and a LAN address
offers them on the https one only.

The challenge each ceremony signs is kept by the caller (the web layer keeps it in the session) and used once.
"""

import ipaddress
import json
import logging
import secrets as random
from dataclasses import dataclass
from urllib.parse import urlsplit

import webauthn
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, AuthenticatorTransport, PublicKeyCredentialDescriptor, ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.db import Database
from app.db.models import User
from app.db.repositories import passkeys as repo
from app.db.repositories import users as users_repo
from app.errors import InvalidInput, NotFound
from app.passwords import verify_password
from app.settings import Settings, origin_of

log = logging.getLogger("reader.passkeys")

CEREMONY_SECONDS = 5 * 60  # how long a challenge stays usable
NAME_LENGTH = 60
_TRANSPORTS = {t.value for t in AuthenticatorTransport}


@dataclass(frozen=True, slots=True)
class Party:
    """Who the passkey is for: the address's host name (rp_id) and its full origin, as the browser will report it."""
    rp_id: str
    origin: str


def relying_party(settings: Settings, request_url: str) -> Party | None:
    """The party for the address this request came in on, when passkeys can work there: one of BASE_URL's addresses,
    https or localhost, and a name rather than an IP address. None otherwise."""
    wanted = origin_of(request_url)
    if not any(origin_of(url) == wanted for url in settings.base_urls):
        return None
    parts = urlsplit(wanted)
    host = (parts.hostname or "").lower()
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return None  # browsers refuse passkeys for an IP address
    except ValueError:
        pass
    if parts.scheme != "https" and host != "localhost":
        return None
    return Party(rp_id=host, origin=wanted)


def unavailable_reason(settings: Settings) -> str:
    https = [url for url in settings.base_urls if url.startswith("https://")]
    if https:
        return f"Passkeys work at your server's https address. Open FeedStash at {https[0]} to add one."
    return "Passkeys need FeedStash at an https address (a reverse proxy in front of it gives it one)."


# ------------------------------------------------------------------ adding one (Settings → You)


def registration_options(db: Database, user: User, party: Party) -> tuple[dict, str, str]:
    """What the browser needs to make a passkey, plus the challenge and the account's user handle to keep for
    register()."""
    with db.transaction() as conn:
        existing = repo.for_user(conn, user.id)
        handle = repo.user_handle(conn, user.id) or bytes_to_base64url(random.token_bytes(16))
    options = webauthn.generate_registration_options(
        rp_id=party.rp_id, rp_name="FeedStash", user_name=user.email, user_id=base64url_to_bytes(handle),
        user_display_name=user.name or user.email, timeout=CEREMONY_SECONDS * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        # Not the same device twice: the browser says it already has one.
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in existing if p.rp_id == party.rp_id
        ],
    )
    return json.loads(webauthn.options_to_json(options)), bytes_to_base64url(options.challenge), handle


def _check_password(db: Database, user: User, password: str) -> None:
    """Accounts with a password confirm it before adding a passkey: a passkey is a way in that lasts."""
    with db.transaction() as conn:
        stored = users_repo.get_password_hash(conn, user.id)
    if stored is not None and not verify_password(password or "", stored):
        raise InvalidInput("Your password isn't right")


def _name(name: str) -> str:
    cleaned = " ".join((name or "").split())[:NAME_LENGTH]
    return cleaned or "Passkey"


def register(
    db: Database, user: User, party: Party, *, credential: dict, challenge: str, handle: str, name: str, password: str,
    now: int,
) -> repo.Passkey:
    _check_password(db, user, password)
    try:
        verified = webauthn.verify_registration_response(
            credential=credential, expected_challenge=base64url_to_bytes(challenge), expected_rp_id=party.rp_id,
            expected_origin=party.origin, require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.info("A passkey for account %s wasn't added: %s", user.id, exc)
        raise InvalidInput("That passkey couldn't be added. Try again, or try another device.") from None
    response = credential.get("response") if isinstance(credential, dict) else None
    transports = [t for t in (response or {}).get("transports") or [] if t in _TRANSPORTS]
    with db.transaction() as conn:
        handle = repo.user_handle(conn, user.id) or handle  # one handle per account, from its first passkey
        credential_id = bytes_to_base64url(verified.credential_id)
        if repo.by_credential(conn, credential_id):
            raise InvalidInput("That passkey is already added")
        return repo.add(
            conn, user.id, credential_id=credential_id, public_key=verified.credential_public_key,
            sign_count=verified.sign_count, transports=transports, user_handle=handle, rp_id=party.rp_id,
            name=_name(name), now=now,
        )


# ------------------------------------------------------------------ signing in


def authentication_options(party: Party) -> tuple[dict, str]:
    """No list of passkeys: the browser offers the ones it has for this address, so nobody types an email."""
    options = webauthn.generate_authentication_options(
        rp_id=party.rp_id, timeout=CEREMONY_SECONDS * 1000, user_verification=UserVerificationRequirement.REQUIRED)
    return json.loads(webauthn.options_to_json(options)), bytes_to_base64url(options.challenge)


def authenticate(db: Database, party: Party, *, credential: dict, challenge: str, now: int) -> int:
    """The account a passkey signs in, after checking its signature over the challenge. Raises InvalidInput."""
    try:
        credential_id = bytes_to_base64url(base64url_to_bytes(str(credential["rawId"])))
    except (KeyError, TypeError, ValueError):
        raise InvalidInput("That didn't look like a passkey") from None
    with db.transaction() as conn:
        found = repo.by_credential(conn, credential_id)
    if found is None or found.rp_id != party.rp_id:
        raise InvalidInput("That passkey isn't set up on this server. It may have been removed in Settings. "
                           "Sign in another way, then add it again.")
    response = credential.get("response")
    handle = response.get("userHandle") if isinstance(response, dict) else None
    if handle and handle != found.user_handle:
        raise InvalidInput("That passkey doesn't belong to the account it says it does")
    try:
        verified = webauthn.verify_authentication_response(
            credential=credential, expected_challenge=base64url_to_bytes(challenge), expected_rp_id=party.rp_id,
            expected_origin=party.origin, credential_public_key=found.public_key,
            credential_current_sign_count=found.sign_count, require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.info("A passkey sign-in for account %s was refused: %s", found.user_id, exc)
        raise InvalidInput("That passkey couldn't be checked. Try again, or sign in another way.") from None
    with db.transaction() as conn:
        repo.used(conn, found.id, sign_count=verified.new_sign_count, now=now)
    return found.user_id


# ------------------------------------------------------------------ the list in Settings


def list_for(db: Database, user_id: int) -> list[repo.Passkey]:
    with db.transaction() as conn:
        return repo.for_user(conn, user_id)


def rename(db: Database, user_id: int, passkey_id: int, name: str) -> None:
    with db.transaction() as conn:
        if not repo.rename(conn, user_id, passkey_id, _name(name)):
            raise NotFound("No such passkey")


def remove(db: Database, user_id: int, passkey_id: int) -> None:
    with db.transaction() as conn:
        if not repo.delete(conn, user_id, passkey_id):
            raise NotFound("No such passkey")
