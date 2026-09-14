# Reader

A small self-hosted RSS/Atom reader modeled on Feedly's layout. It runs as one Docker container, stores everything in SQLite, and uses Google sign-in.

## Features

- **Google sign-in (OIDC).** Only the emails or domains you allow can sign in. Each user gets their own feeds and read state.
- **Folders.** Create, rename and delete folders. Drag folders and feeds in the sidebar to reorder them, or drop a feed on a folder to move it. The `⋯` menus also have Move up/down and Sort A–Z, and the **Organize feeds** page has arrow buttons.
- **Feeds.** Follow a site or feed URL; the reader finds the feed itself. Rename, move and unfollow feeds from the same places.
- **Mark as read.** Mark everything as read, or only articles older than 12 hours, 1 day or 1 week. This works on All, a folder or a single feed, and there's an Undo.
- **Mark as read while scrolling.** An article is marked read once it scrolls off the top of the list. You can turn this off in the View menu.
- **Read later.** Star articles to keep them; starred articles are never deleted by cleanup.
- **Views.** Magazine or titles-only layout, newest or oldest first, unread only or all articles. Articles open in place.
- **OPML import and export**, so you can bring your Feedly subscriptions over.
- **Keyboard shortcuts:** `j`/`k` open next/previous, `n`/`p` select without opening, `o` or Enter open/close, `v` open original, `m` toggle read, `s` read later, `r` refresh, `Shift+A` mark all read, `Esc` close.
- **Auto-refresh.** The server fetches feeds in the background, using ETag and Last-Modified to skip unchanged feeds. The page checks for new articles every minute: if you're at the top of the list they appear on their own, otherwise a "↑ N new articles" button shows up.

## 1. Create a Google OAuth client

1. Open [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials). Create a project if you don't have one.
2. Set up the **OAuth consent screen**: choose External, fill in the app name and your email, and add yourself as a test user. You can leave the app in "Testing" for personal use.
3. Click **Create credentials → OAuth client ID** and choose **Web application**.
4. Under **Authorized redirect URIs**, add `<BASE_URL>/auth/callback`, for example:
   - `http://localhost:8651/auth/callback` for local use
   - `https://reader.example.com/auth/callback` behind your reverse proxy
5. Copy the client ID and client secret.

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set these values:

| Variable | Meaning |
|---|---|
| `BASE_URL` | The URL you open the reader at, with no trailing slash. It must match the redirect URI host. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | From step 1. |
| `ALLOWED_EMAILS` | Comma-separated Google accounts that may sign in. |
| `ALLOWED_DOMAINS` | Optional: allow a whole Workspace domain, e.g. `example.com`. |
| `SECRET_KEY` | Signs the session cookie. If empty, one is generated and stored in the data volume. |
| `REFRESH_INTERVAL_MINUTES` | How often the server fetches each feed. Default 15, minimum 5. |
| `RETENTION_DAYS` | Articles older than this are deleted (the newest 50 per feed and all starred articles are kept). Default 90. |

## 3. Run

```bash
docker compose up -d --build
```

Open `BASE_URL` and sign in. Then go to **Organize feeds → Import OPML** and pick the file you exported from Feedly (in Feedly: **Organize → Export OPML**).

Data lives in the `reader-data` Docker volume, in `/data/reader.db`. To back it up:

```bash
docker compose exec reader python -c "import sqlite3; sqlite3.connect('/data/reader.db').execute(\"VACUUM INTO '/data/backup.db'\")"
docker compose cp reader:/data/backup.db ./backup.db
```

### Behind a reverse proxy (HTTPS)

Set `BASE_URL=https://your.domain` so the session cookie is marked `Secure`, and point the proxy at port 8651. To use a different host port, change the left side of `ports` in `docker-compose.yml`. Example Caddyfile:

```
reader.example.com {
    reverse_proxy localhost:8651
}
```

## Trying it without Google

Set `DEV_LOGIN=true` to skip Google and sign in as a local user. **Anyone who can reach the server can then sign in**, so only use it on your own machine.

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
DEV_LOGIN=true uvicorn --factory app.main:create_app --port 8651
# PowerShell: $env:DEV_LOGIN="true"; uvicorn --factory app.main:create_app --port 8651
```

## How it's built

Dependencies point one way: `web` → `services` → `feeds` → `db`. Lower layers never import higher ones.

```
app/
  main.py            create_app(): wires settings, database, scheduler, middleware and routers
  settings.py        typed, validated configuration (pydantic-settings)
  errors.py          domain errors (InvalidInput, NotFound, Conflict); the web layer maps them to 400/404/409
  opml.py            OPML parse/build, pure functions

  db/
    database.py      connections; one transaction per unit of work
    migrations.py    versioned schema changes, tracked in PRAGMA user_version
    models.py        plain dataclasses returned by the repositories
    repositories/    all SQL lives here, one module per table (users, folders, feeds, articles)

  feeds/
    parser.py        RSS/Atom bytes -> ParsedFeed (feedparser, sanitizing). No I/O.
    fetcher.py       HTTP only: conditional GETs and feed discovery. No database.
    ingest.py        stores fetch results; refreshes batches of feeds concurrently
    scheduler.py     background loop: refresh due feeds, purge old articles

  services/
    subscriptions.py following a feed (discover + store), importing OPML

  web/
    api/             JSON routers: tree, articles, folders, feeds, opml
    schemas.py       request and response models
    auth.py          Google OIDC, allowlist, session user
    deps.py          FastAPI dependencies (settings, database, signed-in user)
    pages.py         the app page, login page, health check
    security.py      CSRF check and security headers
    errors.py        error -> JSON response mapping

  static/            the single-page UI (plain JavaScript, no build step)
```

The background refresher runs inside the web process, so run a single process (the Docker image does). If you ever run several, set `SCHEDULER_ENABLED=false` on all but one.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                # unit tests + API tests
READER_E2E_BROWSER="/path/to/chrome" pytest   # also run the browser tests (Chrome or Edge)
```

- `tests/unit/` tests each layer directly: settings, parser, fetcher (with a mock HTTP transport), migrations, repositories, ingest.
- `tests/test_*.py` start the real server on a free port with a fresh database and a local feed server, and exercise the HTTP API.
- `tests/e2e/` drive a headless browser: scroll-to-mark-read, drag-and-drop ordering, auto-refresh.

**Security notes**

- Feed HTML is sanitized twice: by feedparser on the server and again in the browser. On top of that, a strict Content-Security-Policy blocks all scripts except the app's own.
- State-changing API calls require a custom header, and the session cookie is `SameSite=Lax`.
- Any signed-in user can make the server fetch any http(s) URL when adding a feed. Only allow accounts you trust.
