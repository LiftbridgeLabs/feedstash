"""Signing in: passwords, Google and any OpenID Connect provider for the web app; API tokens for the clients.

Who may use the app: accounts with a FeedStash password (created on purpose), and anyone whose Google or OIDC
email is in ALLOWED_EMAILS / ALLOWED_DOMAINS.
"""

import logging

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.db import Database
from app.db.models import User
from app.db.repositories import tokens as tokens_repo
from app.db.repositories import users as users_repo
from app.services import accounts
from app.settings import Settings
from app.web.ratelimit import LoginLimiter
from app.web.schemas import OkOut, PasswordLoginIn, SetupIn

log = logging.getLogger("reader.auth")

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
DEV_LOGIN_SUB = "dev-login"
SESSION_USER_KEY = "uid"
PROVIDERS = ("google", "oidc")
# Errors a provider can cause while we fetch its metadata, keys or tokens.
PROVIDER_ERRORS = (OAuthError, httpx.HTTPError, ValueError, KeyError)

router = APIRouter()


def build_oauth(settings: Settings) -> OAuth | None:
    """OAuth clients for the configured external providers, or None when there are none."""
    if not (settings.google_configured or settings.oidc_configured):
        return None
    oauth = OAuth()
    if settings.google_configured:
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            server_metadata_url=GOOGLE_DISCOVERY_URL,
            client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
        )
    if settings.oidc_configured:
        oauth.register(
            name="oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret.get_secret_value(),
            server_metadata_url=settings.oidc_discovery_url,
            client_kwargs={"scope": settings.oidc_scopes, "code_challenge_method": "S256"},
        )
    return oauth


def external_providers(settings: Settings) -> list[tuple[str, str]]:
    """(provider, button label) for each configured external sign-in."""
    providers = []
    if settings.google_configured:
        providers.append(("google", "Sign in with Google"))
    if settings.oidc_configured:
        providers.append(("oidc", f"Sign in with {settings.oidc_name}"))
    return providers


def email_allowed(settings: Settings, email: str) -> bool:
    if settings.dev_login:
        return True
    email = (email or "").strip().lower()
    if "*" in settings.allowed_emails or email in settings.allowed_emails:
        return True
    return email.rsplit("@", 1)[-1] in settings.allowed_domains


def user_allowed(settings: Settings, user: User) -> bool:
    return user.has_password or email_allowed(settings, user.email)


def session_user(request: Request) -> User | None:
    """The signed-in user, re-checked on every request (accounts can be removed, allowlists changed)."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    with db.transaction() as conn:
        user = users_repo.get(conn, user_id)
    if user is None or not user_allowed(settings, user):
        request.session.clear()
        return None
    return user


def bearer_token(request: Request) -> str | None:
    """A token from `Authorization: Bearer ...`, or from `?token=` on reads (so a URL can carry one)."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    if request.method in ("GET", "HEAD"):
        return request.query_params.get("token") or None
    return None


def token_user(request: Request, token: str) -> User | None:
    """The user an API token belongs to. Remembers which token was used on `request.state.api_token`."""
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    with db.transaction() as conn:
        match = tokens_repo.authenticate(conn, token, now=now())
        user = users_repo.get(conn, match.user_id) if match else None
    if user is None or not user_allowed(settings, user):
        return None
    request.state.api_token = match
    return user


def _start_session(request: Request, user_id: int) -> None:
    request.session.clear()  # a fresh session on every sign-in
    request.session[SESSION_USER_KEY] = user_id


# ------------------------------------------------------------------ Google and OIDC


@router.get("/auth/login")
async def login(request: Request):
    """Signs straight in with DEV_LOGIN, or goes to the only sign-in method there is; otherwise the sign-in page."""
    settings: Settings = request.app.state.settings
    if settings.dev_login:
        db: Database = request.app.state.db

        def upsert() -> int:
            with db.transaction() as conn:
                return users_repo.upsert(conn, sub=DEV_LOGIN_SUB, email="dev@localhost", name="Local user", picture=None)

        _start_session(request, await run_in_threadpool(upsert))
        return RedirectResponse("/", status_code=303)
    providers = external_providers(settings)
    if len(providers) == 1 and not settings.password_login:
        return RedirectResponse(f"/auth/login/{providers[0][0]}", status_code=303)
    return RedirectResponse("/", status_code=303)


def _client(request: Request, provider: str):
    oauth: OAuth | None = request.app.state.oauth
    if provider not in PROVIDERS or oauth is None:
        return None
    return oauth.create_client(provider)


@router.get("/auth/login/{provider}")
async def login_with(provider: str, request: Request):
    settings: Settings = request.app.state.settings
    client = _client(request, provider)
    if client is None:
        return RedirectResponse("/?error=not_configured", status_code=303)
    extra = {"prompt": "select_account"} if provider == "google" else {}
    try:
        return await client.authorize_redirect(request, f"{settings.base_url}/auth/{provider}/callback", **extra)
    except PROVIDER_ERRORS as exc:
        log.warning("Couldn't start %s sign-in: %s", provider, exc)
        return RedirectResponse("/?error=oauth", status_code=303)


@router.get("/auth/callback")
async def google_callback_before_oidc(request: Request):
    """The Google redirect URI from before other providers existed."""
    return await _finish_external_sign_in(request, "google")


@router.get("/auth/{provider}/callback")
async def provider_callback(provider: str, request: Request):
    return await _finish_external_sign_in(request, provider)


def _verified(value) -> bool | None:
    """The email_verified claim as a bool, or None when the provider didn't send it. Some send it as a string."""
    if value is None:
        return None
    return value if isinstance(value, bool) else str(value).strip().lower() == "true"


async def _finish_external_sign_in(request: Request, provider: str):
    settings: Settings = request.app.state.settings
    client = _client(request, provider)
    if client is None:
        return RedirectResponse("/?error=not_configured", status_code=303)
    try:
        token = await client.authorize_access_token(request)
        info = dict(token.get("userinfo") or {})
        if not info.get("email") and client.server_metadata.get("userinfo_endpoint"):
            info = {**dict(await client.userinfo(token=token)), **info}  # some providers keep the email out of the ID token
    except PROVIDER_ERRORS as exc:
        log.warning("%s sign-in failed: %s", provider, exc)
        return RedirectResponse("/?error=oauth", status_code=303)

    email = str(info.get("email") or "").strip().lower()
    verified = _verified(info.get("email_verified"))
    # Google always says whether the address is verified; other providers may leave it out, which we accept.
    if not info.get("sub") or not email or verified is False or (provider == "google" and not verified):
        return RedirectResponse("/?error=unverified", status_code=303)

    db: Database = request.app.state.db

    def sign_in() -> int | None:
        with db.transaction() as conn:
            existing = users_repo.find_by_email(conn, email)
            if not (email_allowed(settings, email) or (existing and existing.has_password)):
                return None
            return users_repo.upsert(
                conn, sub=f"{provider}:{info['sub']}", email=email, name=info.get("name"),
                picture=info.get("picture"), link_by_email=True,
            )

    user_id = await run_in_threadpool(sign_in)
    if user_id is None:
        log.warning("Rejected %s sign-in from %s (not in ALLOWED_EMAILS/ALLOWED_DOMAINS)", provider, email)
        return RedirectResponse("/?error=not_allowed", status_code=303)
    _start_session(request, user_id)
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------ passwords


@router.post("/auth/password", response_model=OkOut)
async def password_sign_in(body: PasswordLoginIn, request: Request) -> OkOut:
    settings: Settings = request.app.state.settings
    if not settings.password_login:
        raise HTTPException(status_code=404, detail="Password sign-in is turned off")
    limiter: LoginLimiter = request.app.state.login_limiter
    address = request.client.host if request.client else "unknown"
    if wait := limiter.retry_after(address, body.email):
        minutes = max(1, round(wait / 60))
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed sign-ins. Try again in {minutes} minute{'' if minutes == 1 else 's'}.",
            headers={"Retry-After": str(wait)},
        )
    user = await run_in_threadpool(accounts.authenticate, request.app.state.db, body.email, body.password)
    if user is None:
        limiter.record_failure(address, body.email)
        raise HTTPException(status_code=401, detail="Wrong email or password")
    limiter.clear_account(body.email)
    _start_session(request, user.id)
    return OkOut()


@router.post("/auth/setup", response_model=OkOut)
async def first_run_setup(body: SetupIn, request: Request) -> OkOut:
    """Creates the first account (an admin) and signs in. Only works while nobody exists yet."""
    settings: Settings = request.app.state.settings
    if not settings.password_login or settings.dev_login:
        raise HTTPException(status_code=404, detail="Setup isn't available")
    if (settings.allowed_emails or settings.allowed_domains) and not email_allowed(settings, body.email):
        raise HTTPException(status_code=403, detail="Use an email address from ALLOWED_EMAILS or ALLOWED_DOMAINS")
    user = await run_in_threadpool(
        lambda: accounts.setup_first_account(
            request.app.state.db, email=body.email, name=body.name, password=body.password
        )
    )
    _start_session(request, user.id)
    return OkOut()


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
