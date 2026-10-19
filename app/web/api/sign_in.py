"""For admins: the sign-in providers people can use, and who may use them (Settings → Sign-in).

Session-only, like the other admin settings: a phone's token can't add a way in.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.db import Database
from app.db.models import User
from app.db.repositories import app_settings as app_settings_repo
from app.db.repositories import sign_in_providers as providers_repo
from app.errors import InvalidInput
from app.web.deps import DatabaseDep, SessionUserDep
from app.web.schemas import AllowedListIn, SignInOut, SignInProviderIn, SignInProviderOut, SignInProviderPatch
from app.web.sso import (
    DEFAULT_SCOPES, GOOGLE_DISCOVERY_URL, SETTINGS_PREFIX, SSO_CALLBACK_PATH, SignIn, check_issuer, split_list,
)

router = APIRouter(prefix="/api/admin/sign-in")


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
            id=None, kind=provider.kind, name=provider.label.removeprefix("Sign in with "),
            issuer="" if provider.kind == "google" else provider.discovery_url, client_id=provider.client_id,
            scopes=provider.scopes, enabled=True, from_server_settings=True,
            callback_urls=_urls(request, provider.callback_path),
        )
        for provider in sign_in.server_providers()
    ]
    with db.transaction() as conn:
        saved = providers_repo.list_all(conn)
    providers += [
        SignInProviderOut(
            id=row.id, kind=row.kind, name=row.name, issuer="" if row.kind == "google" else row.issuer,
            client_id=row.client_id, scopes=row.scopes, enabled=row.enabled, from_server_settings=False,
            secret_unreadable=sign_in.secret_unreadable(row.id), callback_urls=_urls(request, SSO_CALLBACK_PATH),
        )
        for row in saved
    ]
    return SignInOut(
        providers=providers, callback_urls=_urls(request, SSO_CALLBACK_PATH),
        allowed_emails=sign_in.saved_emails, allowed_domains=sign_in.saved_domains,
        server_allowed_emails=list(settings.allowed_emails), server_allowed_domains=list(settings.allowed_domains),
        password_login=settings.password_login,
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
    issuer = GOOGLE_DISCOVERY_URL if body.kind == "google" else await check_issuer(body.issuer)
    secret = request.app.state.secrets.encrypt(body.client_secret.strip())

    def save() -> SignInOut:
        with db.transaction() as conn:
            providers_repo.create(
                conn, kind=body.kind, name=name, issuer=issuer, client_id=body.client_id.strip(),
                client_secret=secret, scopes=_scopes(body.scopes), now=now(),
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
    if body.enabled is not None:
        changes["enabled"] = int(body.enabled)

    def save() -> SignInOut:
        with db.transaction() as conn:
            providers_repo.update(conn, provider_id, now=now(), **changes)
        _reload(request, db)
        return _overview(request, db)

    return await run_in_threadpool(save)


@router.delete("/providers/{provider_id}", status_code=204)
async def remove_provider(provider_id: int, request: Request, user: SessionUserDep, db: DatabaseDep) -> Response:
    _admin(user)

    def remove() -> None:
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
    # Signing in with Google or OIDC is checked against this list on every request, so taking yourself off it
    # (without a password to fall back on) would sign you out on the spot.
    if not user.has_password and not sign_in.email_allowed(user.email, emails=emails, domains=domains):
        raise InvalidInput(
            f"That would sign you out: keep {user.email} on the list, or give yourself a password first."
        )

    def save() -> SignInOut:
        with db.transaction() as conn:
            app_settings_repo.set_many(conn, {
                f"{SETTINGS_PREFIX}allowed_emails": ",".join(emails),
                f"{SETTINGS_PREFIX}allowed_domains": ",".join(domains),
            })
        _reload(request, db)
        return _overview(request, db)

    return await run_in_threadpool(save)
