import html
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.settings import Settings
from app.web.auth import session_user

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

LOGIN_ERRORS = {
    "not_allowed": "That Google account isn't allowed to use this reader.",
    "unverified": "Your Google account email isn't verified.",
    "oauth": "Google sign-in failed. Please try again.",
    "not_configured": "Google sign-in isn't configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
}

router = APIRouter(include_in_schema=False)


def login_page(settings: Settings, error: str | None) -> str:
    message = LOGIN_ERRORS.get(error or "")
    error_html = f'<p class="login-error">{html.escape(message)}</p>' if message else ""
    button = "Continue as local user" if settings.dev_login else "Sign in with Google"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Reader</title><link rel="icon" href="/static/icon.svg"><link rel="stylesheet" href="/static/style.css"></head>
<body class="login-body"><main class="login-card">
<img src="/static/icon.svg" alt="" width="56" height="56"><h1>Reader</h1><p class="muted">Your feeds, without the noise.</p>
{error_html}<a class="btn btn-primary btn-lg" href="/auth/login">{button}</a>
</main></body></html>"""


@router.get("/")
def index(request: Request, error: str | None = None):
    if session_user(request):
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
    return HTMLResponse(login_page(request.app.state.settings, error))


@router.get("/healthz")
def healthz():
    return {"ok": True}
