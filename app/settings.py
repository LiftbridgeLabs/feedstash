"""Typed, validated configuration read from environment variables (see .env.example).

Constructing Settings has no side effects; `resolve_secret_key` is the only function that touches disk.
"""

import contextlib
import logging
import os
import secrets
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger("reader.settings")

# Comma-separated in the environment ("a@x.com, b@y.com"), a list in Python.
CommaSeparated = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_ignore_empty=True)

    # The addresses the app is reached at, comma separated, e.g. "https://feedstash.example.com,http://192.168.1.50:8672".
    # Google/OIDC sign-in comes back to whichever one the browser used; the first is the main address.
    base_urls: CommaSeparated = Field(default_factory=lambda: ["http://localhost:8672"], validation_alias="BASE_URL")
    database_path: Path = Path("data/feedstash.db")
    host: str = "127.0.0.1"
    port: int = Field(default=8672, ge=1, le=65535)
    # Proxies whose X-Forwarded-For/-Proto headers are trusted ("*" = any; fine when only a proxy can reach the app).
    forwarded_allow_ips: str = "127.0.0.1"

    # Accounts with a FeedStash password. The first one is created on the setup page and is an admin.
    password_login: bool = True

    # Google and any other OpenID Connect provider (Authentik, Authelia, Keycloak, Pocket ID...).
    # Their users need an email in ALLOWED_EMAILS or ALLOWED_DOMAINS, or an existing password account.
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_name: str = "single sign-on"
    oidc_scopes: str = "openid email profile"
    allowed_emails: CommaSeparated = Field(default_factory=list)
    allowed_domains: CommaSeparated = Field(default_factory=list)
    # Skips sign-in and signs everyone in as one local user. Never enable on a reachable server.
    dev_login: bool = False

    # Signs session cookies. When unset, a key is generated once and stored next to the database.
    secret_key: SecretStr | None = None
    # Forces session cookies to be Secure (or not). By default they are Secure when served over https.
    cookie_secure: bool | None = None
    session_days: int = Field(default=30, ge=1, le=400)

    refresh_interval_minutes: int = Field(default=15, ge=5, le=24 * 60)
    retention_days: int = Field(default=90, ge=1)
    keep_per_feed: int = Field(default=50, ge=1)
    # Run the background refresher in this process. Keep it on in exactly one process.
    scheduler_enabled: bool = True
    # Fetch the web page behind each saved link: its preview, a readable copy, and its text for search.
    page_capture: bool = True
    # How often a connected mailbox is checked for mail to save (Settings -> Email).
    mail_poll_minutes: int = Field(default=5, ge=1, le=24 * 60)
    # Set by the Docker image from the release tag; shown in the sidebar and /api/health.
    feedstash_version: str = "dev"

    @field_validator("base_urls", mode="before")
    @classmethod
    def _split_base_urls(cls, value: object) -> list[str]:
        items = value.split(",") if isinstance(value, str) else list(value or [])
        urls: list[str] = []
        for item in items:
            url = str(item).strip().rstrip("/")
            if not url:
                continue
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"{url!r} must start with http:// or https://")
            if url not in urls:
                urls.append(url)
        if not urls:
            raise ValueError("needs at least one address")
        return urls

    @field_validator("oidc_issuer")
    @classmethod
    def _check_issuer(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value

    @field_validator("allowed_emails", "allowed_domains", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> list[str]:
        items = value.split(",") if isinstance(value, str) else list(value or [])
        return [str(item).strip().lower() for item in items if str(item).strip()]

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret.get_secret_value())

    @property
    def oidc_discovery_url(self) -> str:
        """OIDC_ISSUER may be the issuer itself or the full URL of its discovery document."""
        suffix = "/.well-known/openid-configuration"
        return self.oidc_issuer if self.oidc_issuer.endswith(suffix) else self.oidc_issuer + suffix

    @property
    def base_url(self) -> str:
        """The main address: the first one in BASE_URL."""
        return self.base_urls[0]

    def base_url_for(self, origin: str) -> str:
        """The configured address a request came in on (compared as scheme://host:port), or the main address."""
        wanted = _origin(origin)
        return next((url for url in self.base_urls if _origin(url) == wanted), self.base_url)

    @property
    def secure_cookies(self) -> bool | None:
        """Whether session cookies are Secure: as COOKIE_SECURE says, else True when every address is https and False
        when every address is http. None when the addresses mix both: then each response decides by its scheme."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        schemes = {url.split("://", 1)[0] for url in self.base_urls}
        return None if len(schemes) > 1 else schemes == {"https"}

    @property
    def uploads_dir(self) -> Path:
        """Uploaded images live next to the database, so backing up the data directory covers both."""
        return self.database_path.parent / "uploads"


def _origin(url: str) -> str:
    """scheme://host[:port] in lowercase and without a default port, so equivalent spellings compare equal."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:  # IPv6
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    default_port = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}" + (f":{port}" if port and port != default_port else "")


def resolve_secret_key(settings: Settings) -> str:
    """SECRET_KEY if set; otherwise a key generated on first run and kept in the data directory."""
    if settings.secret_key and settings.secret_key.get_secret_value():
        return settings.secret_key.get_secret_value()
    path = settings.database_path.resolve().parent / "secret.key"
    if path.exists():
        # Keys written by earlier releases were readable by everyone; this one signs sessions and encrypts the
        # mailbox password, so only the server's own user may read it.
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(key)
    log.warning("SECRET_KEY not set; generated one at %s", path)
    return key
