"""Application factory. Run with:  python -m app   (or  uvicorn --factory app.main:create_app)"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from app.crypto import SecretBox
from app.db import Database
from app.feeds.scheduler import RefreshScheduler
from app.images import ImageStore
from app.services.mail import MailWorker
from app.services.pages import PageWorker
from app.settings import Settings, resolve_secret_key
from app.web import auth, errors, pages, security
from app.web.api import accounts as accounts_api
from app.web.api import articles as articles_api
from app.web.api import feeds as feeds_api
from app.web.api import folders as folders_api
from app.web.api import greader as greader_api
from app.web.api import imports as imports_api
from app.web.api import mail as mail_api
from app.web.api import opml as opml_api
from app.web.api import stash as stash_api
from app.web.api import stash_organize as stash_organize_api
from app.web.api import tokens as tokens_api
from app.web.api import tree as tree_api
from app.web.ratelimit import LoginLimiter

log = logging.getLogger("feedstash")
# Browsers share cookies across ports on one host, so this must differ from other apps on localhost.
SESSION_COOKIE = "feedstash_session"


MAX_REQUEST_BYTES = 32 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    _configure_logging()
    settings = settings or load_settings()
    db = Database(settings.database_path)
    secrets = SecretBox(resolve_secret_key(settings))
    images = ImageStore(settings.uploads_dir)
    scheduler = RefreshScheduler(db, settings)
    page_worker = PageWorker(db)
    mail_worker = MailWorker(db, images, secrets, settings.mail_poll_minutes)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.initialize()
        _warn_about_sign_in(settings)
        if settings.scheduler_enabled:
            scheduler.start()
            if mail_worker.has_mailboxes():  # nothing to check until someone connects one
                mail_worker.start()
            if settings.page_capture:
                page_worker.start()
        yield
        await scheduler.stop()
        await mail_worker.stop()
        await page_worker.stop()
        for task in list(app.state.background_tasks):
            task.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.images = images
    app.state.secrets = secrets
    app.state.mail_worker = mail_worker
    app.state.oauth = auth.build_oauth(settings)
    app.state.login_limiter = LoginLimiter()
    app.state.background_tasks = set()

    # The largest real upload is a 20 MB image with a few fields; nothing bigger is read into memory. Added first,
    # so it sits innermost: its 413 is raised where the endpoint reads the body, inside the app's error handling.
    app.add_middleware(security.BodySizeLimit, max_bytes=MAX_REQUEST_BYTES)
    security.install(app)
    errors.install(app)
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolve_secret_key(settings),
        session_cookie=SESSION_COOKIE,
        max_age=settings.session_days * 86400,
        same_site="lax",
        https_only=settings.secure_cookies is True,
    )
    if settings.secure_cookies is None:  # both http and https addresses: Secure only on https responses
        app.add_middleware(security.SecureCookieOverHttps, cookie_name=SESSION_COOKIE)
    for router in (
        pages.router, auth.router, tree_api.router, articles_api.router, folders_api.router, feeds_api.router,
        opml_api.router, imports_api.router, stash_api.router, stash_api.uploads_router, stash_organize_api.router,
        mail_api.router, tokens_api.router, accounts_api.router,
    ):
        app.include_router(router)
    # The Google Reader API, for other reader apps. Clients disagree about the address: some take the server's
    # own and add /reader/api/0 themselves (as with Miniflux), others take FreshRSS's /api/greader.php. Both work.
    for prefix in ("", "/api/greader.php"):
        app.include_router(greader_api.router, prefix=prefix)
    app.mount("/static", RevalidatedStaticFiles(directory=pages.STATIC_DIR), name="static")
    return app


class RevalidatedStaticFiles(StaticFiles):
    """Static files the browser must re-check on every load (cheap: ETag), so an update shows up right away
    instead of after the browser's guess at a cache lifetime."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise SystemExit(f"Invalid configuration:\n{exc}") from None


def _configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise every feed fetch is logged


def _warn_about_sign_in(settings: Settings) -> None:
    external = settings.google_configured or settings.oidc_configured
    if settings.dev_login:
        log.warning("DEV_LOGIN is enabled: anyone who can reach this server can sign in")
    elif not (settings.password_login or external):
        log.warning("PASSWORD_LOGIN is off and neither Google nor OIDC is configured; nobody can sign in")
    elif external and not (settings.allowed_emails or settings.allowed_domains):
        log.warning(
            "ALLOWED_EMAILS and ALLOWED_DOMAINS are empty; Google/OIDC sign-ins only work for emails that already "
            "have a password account"
        )
