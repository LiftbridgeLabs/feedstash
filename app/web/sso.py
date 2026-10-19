"""The sign-in providers a server offers and who may use them: Google and OIDC from the server's settings, plus any
an admin adds in Settings → Sign-in.

Providers from the server's settings keep their keys ("google", "oidc") and callback addresses; ones added in
Settings are "p<id>" and all come back to /auth/sso/callback, so an admin can copy that address into the provider
before saving anything here. The allowed list is the server's ALLOWED_EMAILS / ALLOWED_DOMAINS plus whatever an
admin adds in Settings.
"""

import logging
import sqlite3
from dataclasses import dataclass

import httpx
from authlib.integrations.starlette_client import OAuth

from app.crypto import SecretBox
from app.db.models import SignInProvider
from app.db.repositories import app_settings as app_settings_repo
from app.db.repositories import sign_in_providers as providers_repo
from app.errors import InvalidInput
from app.settings import Settings

log = logging.getLogger("reader.auth")

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
DISCOVERY_SUFFIX = "/.well-known/openid-configuration"
DEFAULT_SCOPES = "openid email profile"
SETTINGS_PREFIX = "signin."
SSO_CALLBACK_PATH = "/auth/sso/callback"


@dataclass(frozen=True, slots=True)
class Provider:
    key: str  # "google" / "oidc" from the server's settings, "p<id>" from Settings → Sign-in
    kind: str  # "google" or "oidc"
    label: str  # the button
    discovery_url: str
    client_id: str
    client_secret: str
    scopes: str

    @property
    def account_prefix(self) -> str:
        """What an account's subject is filed under: "<prefix>:<sub>". A subject is only unique at its issuer, so a
        provider added in Settings files under its issuer's address, never its number: a removed provider's
        number coming back, or an edited issuer, mustn't hand one person's account to someone else. Google's
        subjects are the same everywhere, so every Google sign-in shares "google"."""
        if self.kind == "google":
            return "google"
        return "oidc" if self.from_server_settings else f"oidc@{self.discovery_url}"

    @property
    def from_server_settings(self) -> bool:
        return not self.key.startswith("p")

    @property
    def callback_path(self) -> str:
        return f"/auth/{self.key}/callback" if self.from_server_settings else SSO_CALLBACK_PATH


def discovery_url(issuer: str) -> str:
    """An issuer may be given as itself or as the full URL of its discovery document."""
    issuer = issuer.strip().rstrip("/")
    return issuer if issuer.endswith(DISCOVERY_SUFFIX) else issuer + DISCOVERY_SUFFIX


def split_list(value: str | list[str]) -> list[str]:
    """Addresses or domains typed with commas, spaces or new lines between them; lowercased, without repeats."""
    items = value if isinstance(value, list) else value.replace("\n", ",").replace(" ", ",").split(",")
    return list(dict.fromkeys(item.strip().lower().lstrip("@") for item in items if item.strip()))


class SignIn:
    """Kept on app.state.sign_in. Reloaded from the database at startup and after every change in Settings."""

    def __init__(self, settings: Settings, secrets: SecretBox):
        self._settings = settings
        self._secrets = secrets
        # The providers and their authlib clients (built on first use) are replaced together on every reload, so a
        # sign-in always gets a provider and a client from the same moment, even while an admin saves a change.
        self._snapshot: tuple[list[Provider], dict[str, object]] = ([], {})
        self._unreadable: set[int] = set()  # saved providers whose secret this server's key can't open
        self._saved_emails: list[str] = []
        self._saved_domains: list[str] = []
        self._load_server_settings()

    def _load_server_settings(self) -> None:
        settings = self._settings
        self._server_providers = []
        if settings.google_configured:
            self._server_providers.append(Provider(
                "google", "google", "Sign in with Google", GOOGLE_DISCOVERY_URL, settings.google_client_id,
                settings.google_client_secret.get_secret_value(), DEFAULT_SCOPES,
            ))
        if settings.oidc_configured:
            self._server_providers.append(Provider(
                "oidc", "oidc", f"Sign in with {settings.oidc_name}", settings.oidc_discovery_url,
                settings.oidc_client_id, settings.oidc_client_secret.get_secret_value(), settings.oidc_scopes,
            ))
        self._snapshot = (list(self._server_providers), {})

    def load(self, conn: sqlite3.Connection) -> None:
        saved = []
        unreadable = set()
        for row in providers_repo.list_all(conn):
            if not row.enabled:
                continue
            secret = self._secrets.decrypt(row.client_secret)
            if secret is None:
                unreadable.add(row.id)
                log.warning("Sign-in %r is skipped: its client secret can't be read with this SECRET_KEY", row.name)
                continue
            saved.append(self._from_row(row, secret))
        self._snapshot = ([*self._server_providers, *saved], {})
        self._unreadable = unreadable
        values = app_settings_repo.get_all(conn, SETTINGS_PREFIX)
        self._saved_emails = split_list(values.get(f"{SETTINGS_PREFIX}allowed_emails", ""))
        self._saved_domains = split_list(values.get(f"{SETTINGS_PREFIX}allowed_domains", ""))

    @staticmethod
    def _from_row(row: SignInProvider, secret: str) -> Provider:
        url = GOOGLE_DISCOVERY_URL if row.kind == "google" else discovery_url(row.issuer)
        return Provider(f"p{row.id}", row.kind, f"Sign in with {row.name}", url, row.client_id, secret, row.scopes)

    # -------------------------------------------------------------- providers

    def providers(self) -> list[Provider]:
        return list(self._snapshot[0])

    def server_providers(self) -> list[Provider]:
        return list(self._server_providers)

    def secret_unreadable(self, provider_id: int) -> bool:
        return provider_id in self._unreadable

    def resolve(self, key: str):
        """(provider, its authlib client) from one snapshot, or (None, None) when there's no such provider."""
        providers, clients = self._snapshot
        provider = next((provider for provider in providers if provider.key == key), None)
        if provider is None:
            return None, None
        if key not in clients:
            oauth = OAuth()
            oauth.register(
                name=key, client_id=provider.client_id, client_secret=provider.client_secret,
                server_metadata_url=provider.discovery_url,
                client_kwargs={"scope": provider.scopes, "code_challenge_method": "S256"},
            )
            clients[key] = oauth.create_client(key)
        return provider, clients[key]

    # -------------------------------------------------------------- who may sign in

    @property
    def saved_emails(self) -> list[str]:
        return list(self._saved_emails)

    @property
    def saved_domains(self) -> list[str]:
        return list(self._saved_domains)

    def email_allowed(self, email: str, *, emails: list[str] | None = None, domains: list[str] | None = None) -> bool:
        """Whether an address may sign in with Google or OIDC. `emails` / `domains` stand in for the saved lists,
        to test a change before saving it."""
        settings = self._settings
        if settings.dev_login:
            return True
        allowed_emails = {*settings.allowed_emails, *(self._saved_emails if emails is None else emails)}
        allowed_domains = {*settings.allowed_domains, *(self._saved_domains if domains is None else domains)}
        email = (email or "").strip().lower()
        if "*" in allowed_emails or email in allowed_emails:
            return True
        return email.rsplit("@", 1)[-1] in allowed_domains

    @property
    def has_allowed_list(self) -> bool:
        settings = self._settings
        return bool(settings.allowed_emails or settings.allowed_domains or self._saved_emails or self._saved_domains)


async def check_issuer(issuer: str) -> str:
    """Fetches an OIDC provider's discovery document, so a typo is caught when it's saved rather than when someone
    tries to sign in. Returns the issuer, tidied. Admins only reach this: the provider is often on the same network
    (Pocket ID, Authentik), so private addresses are allowed, as they are for OIDC_ISSUER."""
    issuer = issuer.strip().rstrip("/")
    if not issuer.lower().startswith(("http://", "https://")):
        raise InvalidInput("The issuer address has to start with https:// (or http://)")
    url = discovery_url(issuer)
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise InvalidInput(f"Couldn't reach {url}: {exc.__class__.__name__}") from None
    if response.status_code != 200:
        raise InvalidInput(f"{url} answered HTTP {response.status_code}. Check the issuer address.")
    try:
        metadata = response.json()
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict) or not all(
        metadata.get(key) for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")
    ):
        raise InvalidInput(f"{url} isn't an OpenID Connect discovery document. Check the issuer address.")
    return issuer
