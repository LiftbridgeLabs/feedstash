"""Typed, validated configuration read from environment variables (see .env.example).

Constructing Settings has no side effects; `resolve_secret_key` is the only function that touches disk.
"""

import logging
import secrets
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger("reader.settings")

# Comma-separated in the environment ("a@x.com, b@y.com"), a list in Python.
CommaSeparated = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_ignore_empty=True)

    # Public URL the app is served at. Redirect URIs are <base_url>/auth/google/callback and /auth/oidc/callback.
    base_url: str = "http://localhost:8672"
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
    # Defaults to on when base_url is https.
    cookie_secure: bool | None = None
    session_days: int = Field(default=30, ge=1, le=400)

    refresh_interval_minutes: int = Field(default=15, ge=5, le=24 * 60)
    retention_days: int = Field(default=90, ge=1)
    keep_per_feed: int = Field(default=50, ge=1)
    # Run the background refresher in this process. Keep it on in exactly one process.
    scheduler_enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value

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
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://") if self.cookie_secure is None else self.cookie_secure

    @property
    def uploads_dir(self) -> Path:
        """Uploaded images live next to the database, so backing up the data directory covers both."""
        return self.database_path.parent / "uploads"


def resolve_secret_key(settings: Settings) -> str:
    """SECRET_KEY if set; otherwise a key generated on first run and kept in the data directory."""
    if settings.secret_key and settings.secret_key.get_secret_value():
        return settings.secret_key.get_secret_value()
    path = settings.database_path.resolve().parent / "secret.key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    log.warning("SECRET_KEY not set; generated one at %s", path)
    return key
