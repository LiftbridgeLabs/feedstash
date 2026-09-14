"""Google sign-in (OIDC), the email allowlist, and the signed-in user."""

import logging

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.db import Database
from app.db.models import User
from app.db.repositories import users as users_repo
from app.settings import Settings

log = logging.getLogger("reader.auth")

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
DEV_LOGIN_SUB = "dev-login"
SESSION_USER_KEY = "uid"

router = APIRouter()


def build_oauth(settings: Settings) -> OAuth | None:
    if not settings.google_configured:
        return None
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def email_allowed(settings: Settings, email: str) -> bool:
    if settings.dev_login:
        return True
    email = (email or "").lower()
    if "*" in settings.allowed_emails or email in settings.allowed_emails:
        return True
    return email.rsplit("@", 1)[-1] in settings.allowed_domains


def session_user(request: Request) -> User | None:
    """The signed-in user, re-checked against the allowlist on every request."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    with db.transaction() as conn:
        user = users_repo.get(conn, user_id)
    if user is None or not email_allowed(settings, user.email):
        request.session.clear()
        return None
    return user


async def _sign_in(request: Request, *, sub: str, email: str, name: str | None, picture: str | None) -> None:
    db: Database = request.app.state.db

    def upsert() -> int:
        with db.transaction() as conn:
            return users_repo.upsert(conn, sub=sub, email=email, name=name, picture=picture)

    user_id = await run_in_threadpool(upsert)
    request.session.clear()
    request.session[SESSION_USER_KEY] = user_id


@router.get("/auth/login")
async def login(request: Request):
    settings: Settings = request.app.state.settings
    if settings.dev_login:
        await _sign_in(request, sub=DEV_LOGIN_SUB, email="dev@localhost", name="Local user", picture=None)
        return RedirectResponse("/", status_code=303)
    oauth: OAuth | None = request.app.state.oauth
    if oauth is None:
        return RedirectResponse("/?error=not_configured", status_code=303)
    return await oauth.google.authorize_redirect(request, f"{settings.base_url}/auth/callback", prompt="select_account")


@router.get("/auth/callback")
async def callback(request: Request):
    settings: Settings = request.app.state.settings
    oauth: OAuth | None = request.app.state.oauth
    if oauth is None:
        return RedirectResponse("/?error=not_configured", status_code=303)
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        log.warning("OIDC callback failed: %s", exc)
        return RedirectResponse("/?error=oauth", status_code=303)

    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not info.get("sub") or not email or not info.get("email_verified"):
        return RedirectResponse("/?error=unverified", status_code=303)
    if not email_allowed(settings, email):
        log.warning("Rejected sign-in from %s (not in ALLOWED_EMAILS/ALLOWED_DOMAINS)", email)
        return RedirectResponse("/?error=not_allowed", status_code=303)
    await _sign_in(request, sub=info["sub"], email=email, name=info.get("name"), picture=info.get("picture"))
    return RedirectResponse("/", status_code=303)


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
