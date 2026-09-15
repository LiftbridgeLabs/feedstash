import html
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.clock import iso, now
from app.db.repositories import users as users_repo
from app.settings import Settings
from app.web.auth import external_providers, session_user

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

LOGIN_ERRORS = {
    "not_allowed": "That account isn't allowed to use FeedStash.",
    "unverified": "Your account's email address isn't verified.",
    "oauth": "Sign-in didn't work. Please try again.",
    "not_configured": "That sign-in method isn't set up on this server.",
}

# method="post" so that a submit without JavaScript never puts a password in the URL (it's rejected for lacking
# the CSRF header instead); login.js sends the real request.
PASSWORD_FORM = """<form class="login-form" data-login="password" method="post" novalidate>
  <label>Email<input type="email" name="email" autocomplete="username" required autofocus></label>
  <label>Password<input type="password" name="password" autocomplete="current-password" required></label>
  <p class="login-error" data-login-error hidden></p>
  <button class="btn btn-primary btn-lg" type="submit">Sign in</button>
</form>"""

SETUP_FORM = """<form class="login-form" data-login="setup" method="post" novalidate>
  <label>Name<input type="text" name="name" autocomplete="name" maxlength="100" autofocus></label>
  <label>Email<input type="email" name="email" autocomplete="username" required></label>
  <label><span>Password <small>(at least 8 characters)</small></span><input type="password" name="password" autocomplete="new-password" required></label>
  <p class="login-error" data-login-error hidden></p>
  <button class="btn btn-primary btn-lg" type="submit">Create account</button>
</form>"""

router = APIRouter(include_in_schema=False)


def login_page(settings: Settings, *, error: str | None, needs_setup: bool) -> str:
    message = LOGIN_ERRORS.get(error or "")
    options = []
    if settings.dev_login:
        options.append('<a class="btn btn-primary btn-lg" href="/auth/login">Continue as local user</a>')
    for provider, label in external_providers(settings):
        options.append(f'<a class="btn btn-lg" href="/auth/login/{provider}">{html.escape(label)}</a>')
    form = ""
    if settings.password_login and not settings.dev_login:
        form = SETUP_FORM if needs_setup else PASSWORD_FORM
    if not (options or form):
        message = message or "No sign-in method is turned on. Set PASSWORD_LOGIN=true, or configure Google or OIDC."
    tagline = (
        "Create the first account. It becomes the admin." if form == SETUP_FORM
        else "Your feeds, and everything you save for later."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · FeedStash</title><link rel="icon" href="/static/icon.svg"><link rel="stylesheet" href="/static/style.css"></head>
<body class="login-body"><main class="login-card">
<img src="/static/icon.svg" alt="" width="56" height="56"><h1>FeedStash</h1>
<p class="muted">{tagline}</p>
{f'<p class="login-error">{html.escape(message)}</p>' if message else ''}
{form}
{'<div class="login-or"><span>or</span></div>' if form and options else ''}
<div class="login-options">{''.join(options)}</div>
</main>{'<script type="module" src="/static/login.js"></script>' if form else ''}</body></html>"""


@router.get("/")
def index(request: Request, error: str | None = None):
    if session_user(request):
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
    settings: Settings = request.app.state.settings
    with request.app.state.db.transaction() as conn:
        needs_setup = users_repo.count(conn) == 0
    return HTMLResponse(login_page(settings, error=error, needs_setup=needs_setup))


@router.get("/healthz")
def healthz(request: Request):
    """For container health checks: the app answers and can read its database."""
    with request.app.state.db.transaction() as conn:
        conn.execute("SELECT 1 FROM users LIMIT 1").fetchall()
    return {"ok": True}


@router.get("/api/health")
def api_health(request: Request):
    """The clients' "Test connection" check. No sign-in needed."""
    return {"ok": True, "time": iso(now()), "version": request.app.state.settings.feedstash_version}
