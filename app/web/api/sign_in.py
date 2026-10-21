"""For admins: the sign-in providers people can use, and who may use them (Settings → Sign-in).

Session-only, like the other admin settings: a phone's token can't add a way in.
"""

import threading

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.db import Database
from app.db.models import User
from app.db.repositories import app_settings as app_settings_repo
from app.db.repositories import sign_in_providers as providers_repo
from app.errors import InvalidInput
from app.web.deps import DatabaseDep, SessionUserDep
from app.web.schemas import (
    AllowedListIn, SignInOut, SignInProviderIn, SignInProviderOut, SignInProviderPatch, SignInSwitchIn,
)
from app.web.sso import (
    DEFAULT_SCOPES, GOOGLE_DISCOVERY_URL, SETTINGS_PREFIX, SSO_CALLBACK_PATH, SignIn, check_color, check_icon,
    check_issuer, split_list,
)

router = APIRouter(prefix="/api/admin/sign-in")

# Changes here run one at a time, each checking and writing under this lock: two admins turning off the last two
# providers at once mustn't each see the other's as still on (with passwords off, that leaves no way in).
_CHANGES = threading.Lock()


def _admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can change how people sign in")


def _urls(request: Request, path: str) -> list[str]:
    return [f"{base}{path}" for base in request.app.state.settings.base_urls]


def _overview(request: Request, db: Database) -> SignInOut:
    settings = request.app.state.settings
    sign_in: SignIn = request.app.state.sign_in
    providers = [
        SignInProviderOut(
            id=None, key=provider.key, kind=provider.kind, name=provider.label.removeprefix("Sign in with "),
            issuer="" if provider.kind == "google" else provider.discovery_url, client_id=provider.client_id,
            scopes=provider.scopes, icon=provider.icon, color=provider.color, trust_all=provider.trust_all,
            enabled=sign_in.server_provider_enabled(provider.key), from_server_settings=True,
            callback_urls=_urls(request, provider.callback_path),
        )
        for provider in sign_in.server_providers()
    ]
    with db.transaction() as conn:
        saved = providers_repo.list_all(conn)
    providers += [
        SignInProviderOut(
            id=row.id, key=f"p{row.id}", kind=row.kind, name=row.name, issuer="" if row.kind == "google" else row.issuer,
            client_id=row.client_id, scopes=row.scopes, icon=row.icon, color=row.color, trust_all=row.trust_all,
            enabled=row.enabled,
            from_server_settings=False,
            secret_unreadable=sign_in.secret_unreadable(row.id), callback_urls=_urls(request, SSO_CALLBACK_PATH),
        )
        for row in saved
    ]
    return SignInOut(
        sso_enabled=sign_in.sso_enabled, providers=providers, callback_urls=_urls(request, SSO_CALLBACK_PATH),
        allowed_emails=sign_in.saved_emails, allowed_domains=sign_in.saved_domains,
        server_allowed_emails=list(settings.allowed_emails), server_allowed_domains=list(settings.allowed_domains),
        password_login=settings.password_login,
    )


NO_WAY_IN = (
    "Password sign-in is off on this server (PASSWORD_LOGIN=false), so that would leave nobody a way to sign in. "
    "Keep at least one sign-in on."
)


def _ways_in_left(
    request: Request, db: Database, *, sso: bool | None = None, server_off: set[str] | None = None,
    saved: dict[int, bool] | None = None,
) -> bool:
    """Whether someone could still sign in after a change: always, with passwords on; otherwise only while some
    provider stays on. `saved` gives saved providers' new on/off (False for one being removed)."""
    settings = request.app.state.settings
    if settings.password_login or settings.dev_login:
        return True
    sign_in: SignIn = request.app.state.sign_in
    if not (sign_in.sso_enabled if sso is None else sso):
        return False
    if server_off is None:
        server_off = {p.key for p in sign_in.server_providers() if not sign_in.server_provider_enabled(p.key)}
    if any(provider.key not in server_off for provider in sign_in.server_providers()):
        return True
    with db.transaction() as conn:
        rows = providers_repo.list_all(conn)
    return any((saved or {}).get(row.id, row.enabled) and not sign_in.secret_unreadable(row.id) for row in rows)


def _keep_yourself_in(request: Request, user: User, provider_id: int) -> None:
    """Refuses a change that would sign out the admin making it: they got in through this sign-in letting in anyone
    it signs in, and have no password or place on the allowed list to fall back on."""
    sign_in: SignIn = request.app.state.sign_in
    if (not user.has_password and not sign_in.email_allowed(user.email)
            and user.signed_in_with == f"p{provider_id}" and sign_in.trusts(user.signed_in_with)):
        raise InvalidInput(
            f"That would sign you out: you got in through this sign-in. Put {user.email} on the allowed list, or "
            "give yourself a password first."
        )


def _reload(request: Request, db: Database) -> None:
    with db.transaction() as conn:
        request.app.state.sign_in.load(conn)


def _scopes(value: str) -> str:
    scopes = " ".join(dict.fromkeys(value.replace(",", " ").split())) or DEFAULT_SCOPES
    if "openid" not in scopes.split():
        raise InvalidInput("The scopes have to include openid")
    return scopes


def _name(kind: str, name: str) -> str:
    name = " ".join(name.split())
    if kind == "google":
        return "Google"
    if not name:
        raise InvalidInput("Give it a name for the sign-in button, like Pocket ID")
    return name


@router.get("", response_model=SignInOut)
async def overview(request: Request, user: SessionUserDep, db: DatabaseDep) -> SignInOut:
    _admin(user)
    return await run_in_threadpool(_overview, request, db)


@router.post("/providers", response_model=SignInOut, status_code=201)
async def add_provider(body: SignInProviderIn, request: Request, user: SessionUserDep, db: DatabaseDep) -> SignInOut:
    _admin(user)
    name = _name(body.kind, body.name)
    icon, color = check_icon(body.icon), check_color(body.color)
    issuer = GOOGLE_DISCOVERY_URL if body.kind == "google" else await check_issuer(body.issuer)
    secret = request.app.state.secrets.encrypt(body.client_secret.strip())

    def save() -> SignInOut:
        with db.transaction() as conn:
            providers_repo.create(
                conn, kind=body.kind, name=name, issuer=issuer, client_id=body.client_id.strip(),
                client_secret=secret, scopes=_scopes(body.scopes), icon=icon, color=color,
                trust_all=body.trust_all, now=now(),
            )
        _reload(request, db)
        return _overview(request, db)

    return await run_in_threadpool(save)


@router.patch("/providers/{provider_id}", response_model=SignInOut)
async def change_provider(
    provider_id: int, body: SignInProviderPatch, request: Request, user: SessionUserDep, db: DatabaseDep,
) -> SignInOut:
    _admin(user)
    with db.transaction() as conn:
        current = providers_repo.get(conn, provider_id)
    changes: dict = {}
    if body.name is not None:
        changes["name"] = _name(current.kind, body.name)
    if body.issuer is not None and current.kind == "oidc" and body.issuer.strip().rstrip("/") != current.issuer:
        changes["issuer"] = await check_issuer(body.issuer)
    if body.client_id is not None:
        changes["client_id"] = body.client_id.strip()
    if body.client_secret and body.client_secret.strip():
        changes["client_secret"] = request.app.state.secrets.encrypt(body.client_secret.strip())
    if body.scopes is not None:
        changes["scopes"] = _scopes(body.scopes)
    if body.icon is not None:
        changes["icon"] = check_icon(body.icon)
    if body.color is not None:
        changes["color"] = check_color(body.color)
    if body.trust_all is not None:
        changes["trust_all"] = int(body.trust_all)
    if body.enabled is not None:
        changes["enabled"] = int(body.enabled)

    def save() -> SignInOut:
        with _CHANGES:
            if body.enabled is False and not _ways_in_left(request, db, saved={provider_id: False}):
                raise InvalidInput(NO_WAY_IN)
            if body.trust_all is False:
                _keep_yourself_in(request, user, provider_id)
            with db.transaction() as conn:
                providers_repo.update(conn, provider_id, now=now(), **changes)
            _reload(request, db)
            return _overview(request, db)

    return await run_in_threadpool(save)


@router.delete("/providers/{provider_id}", status_code=204)
async def remove_provider(provider_id: int, request: Request, user: SessionUserDep, db: DatabaseDep) -> Response:
    _admin(user)

    def remove() -> None:
        with _CHANGES:
            if not _ways_in_left(request, db, saved={provider_id: False}):
                raise InvalidInput(NO_WAY_IN)
            _keep_yourself_in(request, user, provider_id)
            with db.transaction() as conn:
                providers_repo.delete(conn, provider_id)
            _reload(request, db)

    await run_in_threadpool(remove)
    return Response(status_code=204)


@router.put("/allowed", response_model=SignInOut)
async def set_allowed(body: AllowedListIn, request: Request, user: SessionUserDep, db: DatabaseDep) -> SignInOut:
    _admin(user)
    emails = split_list(body.emails)
    domains = split_list(body.domains)
    if bad := next((email for email in emails if email != "*" and "@" not in email), None):
        raise InvalidInput(f"{bad} isn't an email address. Domains go in the other box.")
    if bad := next((domain for domain in domains if "@" in domain or "." not in domain), None):
        raise InvalidInput(f"{bad} isn't a domain, like example.com")
    sign_in: SignIn = request.app.state.sign_in

    def save() -> SignInOut:
        with _CHANGES:  # checked and saved together, like every other change here
            # Signing in with Google or OIDC is checked against this list on every request, so taking yourself off
            # it (without a password or a sign-in that lets anyone in to fall back on) would sign you out on the spot.
            if (not user.has_password and not sign_in.trusts(user.signed_in_with)
                    and not sign_in.email_allowed(user.email, emails=emails, domains=domains)):
                raise InvalidInput(
                    f"That would sign you out: keep {user.email} on the list, or give yourself a password first."
                )
            with db.transaction() as conn:
                app_settings_repo.set_many(conn, {
                    f"{SETTINGS_PREFIX}allowed_emails": ",".join(emails),
                    f"{SETTINGS_PREFIX}allowed_domains": ",".join(domains),
                })
            _reload(request, db)
            return _overview(request, db)

    return await run_in_threadpool(save)


@router.put("/switch", response_model=SignInOut)
async def switch(body: SignInSwitchIn, request: Request, user: SessionUserDep, db: DatabaseDep) -> SignInOut:
    """Every Google and OIDC button on or off at once, keeping how each is set up (handy for testing)."""
    _admin(user)

    def save() -> SignInOut:
        with _CHANGES:
            if not body.enabled and not _ways_in_left(request, db, sso=False):
                raise InvalidInput(NO_WAY_IN)
            with db.transaction() as conn:
                app_settings_repo.set_many(conn, {f"{SETTINGS_PREFIX}sso": "on" if body.enabled else "off"})
            _reload(request, db)
            return _overview(request, db)

    return await run_in_threadpool(save)


@router.patch("/server/{key}", response_model=SignInOut)
async def switch_server_provider(
    key: str, body: SignInSwitchIn, request: Request, user: SessionUserDep, db: DatabaseDep,
) -> SignInOut:
    """Turns off (or back on) a provider set in the server's settings, which can't be changed from here otherwise."""
    _admin(user)
    sign_in: SignIn = request.app.state.sign_in
    if key not in {provider.key for provider in sign_in.server_providers()}:
        raise HTTPException(status_code=404, detail="That sign-in isn't set in the server's settings")

    def save() -> SignInOut:
        with _CHANGES:
            off = {p.key for p in sign_in.server_providers() if not sign_in.server_provider_enabled(p.key)}
            off = off - {key} if body.enabled else off | {key}
            if not body.enabled and not _ways_in_left(request, db, server_off=off):
                raise InvalidInput(NO_WAY_IN)
            with db.transaction() as conn:
                app_settings_repo.set_many(conn, {f"{SETTINGS_PREFIX}server_off": ",".join(sorted(off))})
            _reload(request, db)
            return _overview(request, db)

    return await run_in_threadpool(save)
