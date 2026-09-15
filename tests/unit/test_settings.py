import pytest
from pydantic import ValidationError

from app.settings import Settings, resolve_secret_key

ENV_KEYS = (
    "BASE_URL", "DATABASE_PATH", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAILS", "ALLOWED_DOMAINS",
    "DEV_LOGIN", "SECRET_KEY", "COOKIE_SECURE", "SESSION_DAYS", "REFRESH_INTERVAL_MINUTES", "RETENTION_DAYS",
    "KEEP_PER_FEED", "SCHEDULER_ENABLED", "HOST", "PORT", "FORWARDED_ALLOW_IPS", "PASSWORD_LOGIN", "OIDC_ISSUER",
    "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_NAME", "OIDC_SCOPES", "FEEDSTASH_VERSION",
)


@pytest.fixture
def settings_from_env(monkeypatch):
    def build(**env: str) -> Settings:
        for key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings()

    return build


def test_defaults(settings_from_env):
    settings = settings_from_env()
    assert settings.base_url == "http://localhost:8672"
    assert settings.uploads_dir == settings.database_path.parent / "uploads"
    assert settings.refresh_interval_minutes == 15
    assert settings.allowed_emails == []
    assert not settings.dev_login
    assert not settings.google_configured
    assert not settings.secure_cookies
    assert settings.scheduler_enabled
    assert (settings.host, settings.port) == ("127.0.0.1", 8672)
    assert settings.password_login and not settings.oidc_configured


def test_oidc_issuer_or_discovery_url(settings_from_env):
    settings = settings_from_env(
        OIDC_ISSUER="https://auth.example.com/application/o/feedstash/", OIDC_CLIENT_ID="id", OIDC_CLIENT_SECRET="s"
    )
    assert settings.oidc_configured
    assert settings.oidc_discovery_url == "https://auth.example.com/application/o/feedstash/.well-known/openid-configuration"
    discovery = "https://id.example.com/.well-known/openid-configuration"
    assert settings_from_env(OIDC_ISSUER=discovery).oidc_discovery_url == discovery
    assert not settings_from_env(OIDC_ISSUER="https://id.example.com", OIDC_CLIENT_ID="id").oidc_configured


def test_values_are_parsed_from_the_environment(settings_from_env):
    settings = settings_from_env(
        BASE_URL="https://reader.example.com/",
        ALLOWED_EMAILS=" Me@Example.com, you@example.com ,",
        ALLOWED_DOMAINS="",
        DEV_LOGIN="true",
        REFRESH_INTERVAL_MINUTES="20",
        GOOGLE_CLIENT_ID="id",
        GOOGLE_CLIENT_SECRET="secret",
        SCHEDULER_ENABLED="false",
    )
    assert settings.base_url == "https://reader.example.com"
    assert settings.allowed_emails == ["me@example.com", "you@example.com"]
    assert settings.allowed_domains == []
    assert settings.dev_login
    assert settings.refresh_interval_minutes == 20
    assert settings.google_configured
    assert settings.secure_cookies
    assert not settings.scheduler_enabled


def test_several_addresses_for_home_and_away(settings_from_env):
    settings = settings_from_env(
        BASE_URL="https://feedstash.example.com/, http://192.168.1.50:8672 ,https://feedstash.example.com"
    )
    assert settings.base_urls == ["https://feedstash.example.com", "http://192.168.1.50:8672"]
    assert settings.base_url == "https://feedstash.example.com"
    assert settings.secure_cookies is None  # decided per request
    assert settings.base_url_for("http://192.168.1.50:8672/") == "http://192.168.1.50:8672"
    assert settings.base_url_for("HTTPS://FeedStash.example.com:443/") == "https://feedstash.example.com"
    assert settings.base_url_for("http://feedstash.example.com/") == "https://feedstash.example.com"  # not listed
    assert settings_from_env(BASE_URL="https://a.example.com,https://b.example.com").secure_cookies is True


def test_secure_cookies_can_be_turned_off_explicitly(settings_from_env):
    assert not settings_from_env(BASE_URL="https://reader.example.com", COOKIE_SECURE="false").secure_cookies


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REFRESH_INTERVAL_MINUTES", "2"),
        ("REFRESH_INTERVAL_MINUTES", "often"),
        ("BASE_URL", "reader.example.com"),
        ("BASE_URL", "https://ok.example.com,reader.example.com"),
        ("BASE_URL", " , "),
        ("DEV_LOGIN", "maybe"),
        ("RETENTION_DAYS", "0"),
        ("PORT", "70000"),
        ("OIDC_ISSUER", "auth.example.com"),
    ],
)
def test_invalid_values_are_rejected(settings_from_env, name, value):
    with pytest.raises(ValidationError):
        settings_from_env(**{name: value})


def test_secrets_are_not_shown_in_repr(settings_from_env):
    settings = settings_from_env(GOOGLE_CLIENT_SECRET="hunter2", SECRET_KEY="also-secret")
    assert "hunter2" not in repr(settings)
    assert "also-secret" not in repr(settings)


def test_building_settings_touches_nothing_on_disk(settings_from_env, tmp_path):
    settings_from_env(DATABASE_PATH=str(tmp_path / "data" / "reader.db"))
    assert not (tmp_path / "data").exists()


def test_secret_key_is_generated_once_then_reused(settings_from_env, tmp_path):
    settings = settings_from_env(DATABASE_PATH=str(tmp_path / "data" / "reader.db"))
    key = resolve_secret_key(settings)
    assert len(key) > 40
    assert resolve_secret_key(settings) == key
    assert (tmp_path / "data" / "secret.key").read_text(encoding="utf-8") == key


def test_explicit_secret_key_wins(settings_from_env, tmp_path):
    settings = settings_from_env(DATABASE_PATH=str(tmp_path / "reader.db"), SECRET_KEY="explicit")
    assert resolve_secret_key(settings) == "explicit"
    assert not (tmp_path / "secret.key").exists()
