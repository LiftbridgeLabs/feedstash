"""Signing in: passwords, Google and any OpenID Connect provider for the web app; API tokens for the clients.

Who may use the app: accounts with a FeedStash password (created on purpose), and anyone whose Google or OIDC
email is on the allowed list (ALLOWED_EMAILS / ALLOWED_DOMAINS, plus Settings → Sign-in). The providers themselves
are in app/web/sso.py.
"""

import asyncio
import html
import ipaddress
import logging
import secrets

import httpx
from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
from app.web.sso import SignIn

log = logging.getLogger("reader.auth")

DEV_LOGIN_SUB = "dev-login"
SESSION_USER_KEY = "uid"
SESSION_VERSION_KEY = "sv"  # see migration 11: a session started before the account's last change doesn't count
SESSION_SSO_KEY = "sso"  # which provider from Settings → Sign-in a sign-in started with (they share one callback)
SESSION_TRY_KEY = "sso_try"  # an admin's Try it: the provider being tried, whose result is shown, not signed in
# Errors a provider can cause while we fetch its metadata, keys or tokens.
PROVIDER_ERRORS = (OAuthError, httpx.HTTPError, ValueError, KeyError)

router = APIRouter()

# Each password check costs scrypt's 32 MB and about a tenth of a second, so a flood of sign-ins could exhaust the
# machine. A few at a time; the rest wait their turn.
PASSWORD_CHECKS = asyncio.Semaphore(4)


def user_allowed(sign_in: SignIn, user: User) -> bool:
    return user.has_password or sign_in.email_allowed(user.email) or sign_in.trusts(user.signed_in_with)


def session_user(request: Request) -> User | None:
    """The signed-in user, re-checked on every request (accounts can be removed, allowlists changed)."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    db: Database = request.app.state.db
    with db.transaction() as conn:
        user = users_repo.get(conn, user_id)
        version = users_repo.session_version(conn, user_id)
    sign_in: SignIn = request.app.state.sign_in
    if user is None or not user_allowed(sign_in, user) or request.session.get(SESSION_VERSION_KEY, 0) != version:
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
    db: Database = request.app.state.db
    with db.transaction() as conn:
        match = tokens_repo.authenticate(conn, token, now=now())
        user = users_repo.get(conn, match.user_id) if match else None
    if user is None or not user_allowed(request.app.state.sign_in, user):
        return None
    request.state.api_token = match
    return user


async def start_session(request: Request, user_id: int, session_version: int | None = None) -> None:
    """Signs this browser in as the user: a fresh session, carrying the account's session number. A password sign-in
    passes the number it read with the password, so a password changed in between doesn't leave this one valid."""
    db: Database = request.app.state.db

    def current() -> int:
        with db.transaction() as conn:
            return users_repo.session_version(conn, user_id) or 0

    version = session_version if session_version is not None else await run_in_threadpool(current)
    request.session.clear()  # a fresh session on every sign-in
    request.session[SESSION_USER_KEY] = user_id
    request.session[SESSION_VERSION_KEY] = version


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

        await start_session(request, await run_in_threadpool(upsert))
        return RedirectResponse("/", status_code=303)
    providers = request.app.state.sign_in.providers()
    if len(providers) == 1 and not settings.password_login:
        return RedirectResponse(f"/auth/login/{providers[0].key}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/auth/login/{provider}")
async def login_with(provider: str, request: Request):
    settings: Settings = request.app.state.settings
    sign_in: SignIn = request.app.state.sign_in
    # Try it (Settings → Sign-in): an admin checks a provider, even one that's turned off, without signing in with it.
    trying = request.query_params.get("try") == "1"
    if trying and not await _is_admin(request):
        return RedirectResponse("/?error=not_configured", status_code=303)
    chosen, client = sign_in.resolve(provider, trying=trying)
    if chosen is None or client is None:
        return RedirectResponse("/?error=not_configured", status_code=303)
    extra = {"prompt": "select_account"} if chosen.kind == "google" else {}
    # Come back to the address the browser is using (LAN or reverse proxy), so the session cookie carries over.
    redirect_uri = f"{settings.base_url_for(str(request.base_url))}{chosen.callback_path}"
    if not chosen.from_server_settings:
        request.session[SESSION_SSO_KEY] = chosen.key
    if trying:
        request.session[SESSION_TRY_KEY] = chosen.key
    else:
        request.session.pop(SESSION_TRY_KEY, None)
    try:
        return await client.authorize_redirect(request, redirect_uri, **extra)
    except PROVIDER_ERRORS as exc:
        log.warning("Couldn't start %s sign-in: %s", chosen.label, exc)
        return RedirectResponse("/?error=oauth", status_code=303)


@router.get("/auth/callback")
async def google_callback_before_oidc(request: Request):
    """The Google redirect URI from before other providers existed."""
    return await _finish_external_sign_in(request, "google")


@router.get("/auth/sso/callback")
async def settings_provider_callback(request: Request):
    """Where every provider added in Settings → Sign-in comes back; the session says which one this is."""
    return await _finish_external_sign_in(request, request.session.pop(SESSION_SSO_KEY, None) or "")


@router.get("/auth/{provider}/callback")
async def provider_callback(provider: str, request: Request):
    if provider.startswith("p"):  # providers from Settings only come back through /auth/sso/callback
        return RedirectResponse("/?error=not_configured", status_code=303)
    return await _finish_external_sign_in(request, provider)


def _verified(value) -> bool | None:
    """The email_verified claim as a bool, or None when the provider didn't send it. Some send it as a string."""
    if value is None:
        return None
    return value if isinstance(value, bool) else str(value).strip().lower() == "true"


async def _finish_external_sign_in(request: Request, provider: str):
    sign_in: SignIn = request.app.state.sign_in
    trying = bool(provider) and request.session.pop(SESSION_TRY_KEY, None) == provider and await _is_admin(request)
    chosen, client = sign_in.resolve(provider, trying=trying)
    if chosen is None or client is None:
        return RedirectResponse("/?error=not_configured", status_code=303)
    try:
        token = await client.authorize_access_token(request)
        info = dict(token.get("userinfo") or {})
        if not info.get("email") and client.server_metadata.get("userinfo_endpoint"):
            info = {**dict(await client.userinfo(token=token)), **info}  # some providers keep the email out of the ID token
    except PROVIDER_ERRORS as exc:
        log.warning("%s failed: %s", chosen.label, exc)
        if trying:
            return _try_result(request, chosen, failed=str(exc) or exc.__class__.__name__)
        return RedirectResponse("/?error=oauth", status_code=303)

    email = str(info.get("email") or "").strip().lower()
    verified = _verified(info.get("email_verified"))
    if trying:
        return await run_in_threadpool(_try_result, request, chosen, info=info, email=email, verified=verified)
    # Google always says whether the address is verified; other providers may leave it out, which is accepted for a
    # new account but not for joining an existing one (see find_or_add_account).
    if not info.get("sub") or not email or verified is False or (chosen.kind == "google" and not verified):
        return RedirectResponse("/?error=unverified", status_code=303)

    db: Database = request.app.state.db

    def find_or_add_account() -> int | str | None:
        with db.transaction() as conn:
            existing = users_repo.find_by_email(conn, email)
            # Joining an account that already exists needs the provider's word that the address is theirs;
            # otherwise whoever could claim that address at the provider would get the account.
            if existing and not users_repo.has_sub(conn, f"{chosen.account_prefix}:{info['sub']}") and verified is not True:
                return "unverified"
            if not (sign_in.email_allowed(email) or chosen.trust_all or (existing and existing.has_password)):
                return None
            user_id = users_repo.upsert(
                conn, sub=f"{chosen.account_prefix}:{info['sub']}", email=email, name=info.get("name"),
                picture=info.get("picture"), link_by_email=True,
            )
            users_repo.set_signed_in_with(conn, user_id, chosen.key)
            return user_id

    user_id = await run_in_threadpool(find_or_add_account)
    if user_id == "unverified":
        log.warning("Rejected %s sign-in to the existing account %s: the provider didn't verify the address", provider, email)
        return RedirectResponse("/?error=unverified", status_code=303)
    if user_id is None:
        log.warning("Rejected %s from %s (not on the allowed list)", chosen.label, email)
        return RedirectResponse("/?error=not_allowed", status_code=303)
    await start_session(request, user_id)
    return RedirectResponse("/", status_code=303)


async def _is_admin(request: Request) -> bool:
    user = await run_in_threadpool(session_user, request)
    return bool(user and user.is_admin)


def _try_result(
    request: Request, chosen, *, failed: str | None = None, info: dict | None = None, email: str = "",
    verified: bool | None = None,
) -> HTMLResponse:
    """What Try it found, on a page of its own (the admin stays signed in as themselves; no account is made)."""
    name = html.escape(chosen.label.removeprefix("Sign in with "))
    settings: Settings = request.app.state.settings
    callback = html.escape(f"{settings.base_url_for(str(request.base_url))}{chosen.callback_path}")
    if failed:
        title = f"{name} didn't finish the sign-in"
        lines = [
            f"What it said: <code>{html.escape(failed[:300])}</code>",
            f"Check the client ID and secret, and that the redirect URI at the provider is <code>{callback}</code>.",
        ]
    elif not (info or {}).get("sub") or not email:
        title = f"{name} answered, but without an email address"
        lines = ["FeedStash needs one to know whose account it is. Make sure the client asks for the "
                 "<code>email</code> scope and that your account there has an address."]
    else:
        title = f"{name} works"
        lines = [f"It signed in <b>{html.escape(email)}</b>."]
        refused = verified is False or (chosen.kind == "google" and not verified)
        if refused:
            lines.append("But it says that address isn't verified, so FeedStash won't accept it.")
        elif verified is None:
            lines.append("It didn't say whether the address is verified. That's fine for a new account, but it can't "
                         "join an account that already exists.")
        db: Database = request.app.state.db
        with db.transaction() as conn:
            existing = users_repo.find_by_email(conn, email)
            linked = users_repo.has_sub(conn, f"{chosen.account_prefix}:{info['sub']}")
        sign_in: SignIn = request.app.state.sign_in
        # The same checks as a real sign-in (find_or_add_account), so the page never promises more than it would do.
        if refused:
            pass
        elif existing and not linked and verified is not True:
            lines.append("That address already has an account here, and without the provider saying it's verified, "
                         "FeedStash won't let this sign-in into it.")
        elif chosen.trust_all:
            lines.append(f"{name} decides who gets in with this sign-in, so they can sign in.")
        elif sign_in.email_allowed(email):
            lines.append("That address is on the allowed list, so they can sign in.")
        elif existing and existing.has_password:
            lines.append("That address has a password account here, so they can sign in.")
        else:
            lines.append("That address isn't on the allowed list yet, so FeedStash would turn them away. Add it "
                         "under <b>Who can sign in</b>.")
        if not chosen.shown:
            lines.append("Its button is hidden right now, so nobody sees it on the sign-in page until you turn it on.")
    body = "".join(f"<p>{line}</p>" for line in lines)
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Try {name} · FeedStash</title><link rel="icon" href="/static/icon.svg"><link rel="stylesheet" href="/static/style.css"></head>
<body class="login-body"><main class="login-card try-result">
<img src="/static/icon.svg" alt="" width="56" height="56"><h1>{title}</h1>
{body}
<p class="muted">You're still signed in as yourself, and no account was made. You can close this tab.</p>
<a class="btn btn-primary btn-lg" href="/#/settings">Back to Settings</a>
</main></body></html>""")


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
    async with PASSWORD_CHECKS:
        found = await run_in_threadpool(accounts.authenticate, request.app.state.db, body.email, body.password)
    if found is None:
        limiter.record_failure(address, body.email)
        raise HTTPException(status_code=401, detail="Wrong email or password")
    user, session_version = found
    limiter.clear_account(body.email)
    await start_session(request, user.id, session_version)
    return OkOut()


# Addresses on the server's own network: loopback, private LAN and Docker ranges, IPv6 unique-local and link-local,
# and 100.64.0.0/10 (Tailscale). Listed rather than ip.is_private, which also counts documentation and reserved
# ranges.
OWN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10",
))


def from_own_network(request: Request) -> bool:
    """Whether the request comes from the server's own network (LAN, Docker, VPN), as far as FeedStash can tell.
    With FORWARDED_ALLOW_IPS=* anyone can claim any address, so then it can't tell, and says no."""
    settings: Settings = request.app.state.settings
    if "*" in [part.strip() for part in settings.forwarded_allow_ips.split(",")]:
        return False
    try:
        ip = ipaddress.ip_address((request.client.host if request.client else "").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in network for network in OWN_NETWORKS)


def setup_needs_token(request: Request) -> bool:
    """First-run setup is open on the server's own network. From anywhere else it needs SETUP_TOKEN, so whoever
    finds a new server on the internet before its owner can't claim it. Once SETUP_TOKEN is set it is always
    required: a Docker gateway or NAT can make an outside visitor look like part of the own network."""
    if request.app.state.settings.setup_token.get_secret_value():
        return True
    return not from_own_network(request)


SETUP_BLOCKED = (
    "For safety, FeedStash can only be set up from your own network. Open it at the server's address on your "
    "network (like http://192.168.1.50:8672) rather than through your domain, or set SETUP_TOKEN in the server's "
    "settings and enter it here."
)


@router.post("/auth/setup", response_model=OkOut)
async def first_run_setup(body: SetupIn, request: Request) -> OkOut:
    """Creates the first account (an admin) and signs in. Only works while nobody exists yet."""
    settings: Settings = request.app.state.settings
    if not settings.password_login or settings.dev_login:
        raise HTTPException(status_code=404, detail="Setup isn't available")
    if setup_needs_token(request):
        expected = settings.setup_token.get_secret_value()
        if not expected:
            raise HTTPException(status_code=403, detail=SETUP_BLOCKED)
        if not secrets.compare_digest((body.setup_token or "").strip().encode(), expected.encode()):
            raise HTTPException(status_code=403, detail="That setup token isn't right")
    sign_in: SignIn = request.app.state.sign_in
    if sign_in.has_allowed_list and not sign_in.email_allowed(body.email):
        raise HTTPException(status_code=403, detail="Use an email address from ALLOWED_EMAILS or ALLOWED_DOMAINS")
    async with PASSWORD_CHECKS:
        user = await run_in_threadpool(
            lambda: accounts.setup_first_account(
                request.app.state.db, email=body.email, name=body.name, password=body.password,
                version=settings.feedstash_version,
            )
        )
    await start_session(request, user.id)
    return OkOut()


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
