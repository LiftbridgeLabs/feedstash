"""The sign-in providers a server offers and who may use them: Google and OIDC from the server's settings, plus any
an admin adds in Settings → Sign-in.

Providers from the server's settings keep their keys ("google", "oidc") and callback addresses; ones added in
Settings are "p<id>" and all come back to /auth/sso/callback, so an admin can copy that address into the provider
before saving anything here. The allowed list is the server's ALLOWED_EMAILS / ALLOWED_DOMAINS plus whatever an
admin adds in Settings.
"""

import html
import logging
import re
import sqlite3
from dataclasses import dataclass, replace

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
BUILT_IN_ICONS = ("key", "shield", "lock", "none")  # app/static/sso/<name>.svg
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True, slots=True)
class Provider:
    key: str  # "google" / "oidc" from the server's settings, "p<id>" from Settings → Sign-in
    kind: str  # "google" or "oidc"
    label: str  # the button
    discovery_url: str
    client_id: str
    client_secret: str
    scopes: str
    icon: str = "key"  # one of BUILT_IN_ICONS, or an image's address; Google's button always has its own look
    color: str = ""  # "#rrggbb", or "" for the theme's
    shown: bool = True  # on the sign-in page; one that's turned off can still be tried from Settings
    trust_all: bool = False  # anyone it signs in may use FeedStash, not only the allowed list

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
        self._sso_enabled = True  # the switch for every Google and OIDC button at once
        self._server_off: set[str] = set()  # providers from the server's settings an admin turned off
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
        values = app_settings_repo.get_all(conn, SETTINGS_PREFIX)
        self._sso_enabled = values.get(f"{SETTINGS_PREFIX}sso", "on") != "off"
        self._server_off = set(split_list(values.get(f"{SETTINGS_PREFIX}server_off", "")))
        for row in providers_repo.list_all(conn):
            secret = self._secrets.decrypt(row.client_secret)
            if secret is None:
                unreadable.add(row.id)
                if row.enabled:
                    log.warning("Sign-in %r is skipped: its client secret can't be read with this SECRET_KEY", row.name)
                continue
            saved.append(replace(self._from_row(row, secret), shown=row.enabled and self._sso_enabled))
        server = [
            replace(provider, shown=provider.key not in self._server_off and self._sso_enabled)
            for provider in self._server_providers
        ]
        self._snapshot = ([*server, *saved], {})
        self._unreadable = unreadable
        self._saved_emails = split_list(values.get(f"{SETTINGS_PREFIX}allowed_emails", ""))
        self._saved_domains = split_list(values.get(f"{SETTINGS_PREFIX}allowed_domains", ""))

    @staticmethod
    def _from_row(row: SignInProvider, secret: str) -> Provider:
        url = GOOGLE_DISCOVERY_URL if row.kind == "google" else discovery_url(row.issuer)
        return Provider(
            f"p{row.id}", row.kind, f"Sign in with {row.name}", url, row.client_id, secret, row.scopes, row.icon,
            row.color, trust_all=row.trust_all and row.kind != "google",  # anyone can have a Google account
        )

    # -------------------------------------------------------------- providers

    def providers(self) -> list[Provider]:
        """The ones on the sign-in page."""
        return [provider for provider in self._snapshot[0] if provider.shown]

    def server_providers(self) -> list[Provider]:
        """All of them, including ones turned off here."""
        return list(self._server_providers)

    def server_provider_enabled(self, key: str) -> bool:
        return key not in self._server_off

    @property
    def sso_enabled(self) -> bool:
        return self._sso_enabled

    def secret_unreadable(self, provider_id: int) -> bool:
        return provider_id in self._unreadable

    def resolve(self, key: str, *, trying: bool = False):
        """(provider, its authlib client) from one snapshot, or (None, None) when there's no such provider on the
        sign-in page. `trying` (an admin's Try it) also finds ones that are turned off."""
        providers, clients = self._snapshot
        provider = next((provider for provider in providers if provider.key == key), None)
        if provider is None or not (provider.shown or trying):
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

    def trusts(self, signed_in_with: str | None) -> bool:
        """Whether the sign-in an account last came through lets in anyone it signs in (turned off or not: turning
        one off hides its button, it doesn't lock out who already uses it). By the sign-in, not the account's
        identity: two clients of one provider share identities, and only the one that let them in counts."""
        return any(
            provider.trust_all and provider.key == signed_in_with for provider in self._snapshot[0]
        )

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


def check_icon(value: str) -> str:
    value = (value or "key").strip()
    if value in BUILT_IN_ICONS:
        return value
    if value.lower().startswith(("https://", "http://")) and len(value) <= 500 and not re.search(r"[\s\"'<>]", value):
        return value
    raise InvalidInput("The icon has to be one of the built-in ones, or an image's address starting with https://")


def check_color(value: str) -> str:
    value = (value or "").strip()
    if value and not _COLOR.match(value):
        raise InvalidInput("The color has to look like #3355ff")
    return value.lower()


def text_color(background: str) -> str:
    """Dark or light text, whichever reads better on the button's color (WCAG relative luminance)."""
    def channel(hex_pair: str) -> float:
        c = int(hex_pair, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(background[i:i + 2]) for i in (1, 3, 5))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1f1f1f" if luminance > 0.179 else "#ffffff"


def button_html(provider: Provider) -> str:
    """A provider's button on the sign-in page. static/js/signinsettings.js draws the same for its preview."""
    label = f"<span>{html.escape(provider.label)}</span>"
    href = f"/auth/login/{html.escape(provider.key)}"
    if provider.kind == "google":  # Google's rules: its own G on a white button
        return f'<a class="btn btn-lg sso-btn sso-google" href="{href}"><img src="/static/sso/google.svg" alt="" width="18" height="18">{label}</a>'
    if provider.icon == "none":
        icon = ""
    elif provider.icon in BUILT_IN_ICONS:
        icon = f'<span class="sso-icon" style="--icon: url(/static/sso/{provider.icon}.svg)"></span>'
    else:
        icon = f'<img src="{html.escape(provider.icon)}" alt="" width="18" height="18" referrerpolicy="no-referrer">'
    style = f' style="--sso-bg: {provider.color}; --sso-fg: {text_color(provider.color)}"' if provider.color else ""
    colored = " sso-colored" if provider.color else ""
    return f'<a class="btn btn-lg sso-btn{colored}" href="{href}"{style}>{icon}{label}</a>'


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
