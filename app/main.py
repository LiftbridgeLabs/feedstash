"""Application factory. Run with:  uvicorn --factory app.main:create_app"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from app.db import Database
from app.feeds.scheduler import RefreshScheduler
from app.settings import Settings, resolve_secret_key
from app.web import auth, errors, pages, security
from app.web.api import articles as articles_api
from app.web.api import feeds as feeds_api
from app.web.api import folders as folders_api
from app.web.api import opml as opml_api
from app.web.api import tree as tree_api

log = logging.getLogger("reader")


def create_app(settings: Settings | None = None) -> FastAPI:
    _configure_logging()
    settings = settings or _load_settings()
    db = Database(settings.database_path)
    scheduler = RefreshScheduler(db, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.initialize()
        _warn_about_sign_in(settings)
        if settings.scheduler_enabled:
            scheduler.start()
        yield
        await scheduler.stop()
        for task in list(app.state.background_tasks):
            task.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.oauth = auth.build_oauth(settings)
    app.state.background_tasks = set()

    security.install(app)
    errors.install(app)
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolve_secret_key(settings),
        session_cookie="reader_session",
        max_age=settings.session_days * 86400,
        same_site="lax",
        https_only=settings.secure_cookies,
    )
    for router in (
        pages.router, auth.router, tree_api.router, articles_api.router,
        folders_api.router, feeds_api.router, opml_api.router,
    ):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=pages.STATIC_DIR), name="static")
    return app


def _load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise SystemExit(f"Invalid configuration:\n{exc}") from None


def _configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise every feed fetch is logged


def _warn_about_sign_in(settings: Settings) -> None:
    if settings.dev_login:
        log.warning("DEV_LOGIN is enabled: anyone who can reach this server can sign in")
    elif not settings.google_configured:
        log.warning("GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set; nobody can sign in")
    elif not (settings.allowed_emails or settings.allowed_domains):
        log.warning("ALLOWED_EMAILS and ALLOWED_DOMAINS are empty; every sign-in will be rejected")
