# Working on FeedStash (server)

FeedStash is a self-hosted feed reader combined with a read-later "stash". `README.md` is the operator's guide —
features, configuration, deployment, the client API. This file is for changing the code.

Product decisions, the maintainer's own deployment and the roadmap live in the private companion repo,
`LiftbridgeLabs/feedstash-apps`, in its `CLAUDE.md`. If both repos are checked out side by side, read that too.

## Layout and layering

Dependencies point one way: **web → services → (feeds, pages, mail) → db**. Lower layers never import higher ones.

- `app/db/` — `migrations.py` (numbered, append-only), `models.py` (plain frozen dataclasses), and
  `repositories/`, which is **the only place SQL lives**. One transaction per unit of work (`db.transaction()`).
- `app/feeds/` — `parser` (no I/O), `fetcher` (HTTP only), `ingest` (storing entries), `scheduler`, `to_stash`.
- `app/pages/` — fetching a saved link and extracting its preview and readable copy with trafilatura.
- `app/mail/` — the IMAP client and message parser (no database).
- `app/services/` — orchestration: `accounts`, `subscriptions`, `stash`, `bookmarks`, `pages` (PageWorker),
  `mail` (MailWorker).
- `app/web/` — `api/` routers (thin: parse, call a repository or service, shape the response), `auth.py`,
  `security.py` (CSRF + headers), `errors.py` (domain errors → HTTP), `deps.py`, `schemas.py` (pydantic).
- Pure helpers at the top: `greader.py` (Google Reader API names), `markers.py` (`$Folder` / `#tag` in email),
  `crypto.py` (SecretBox), `text.py`, `opml.py`, `images.py`.
- `app/static/` — the web app: vanilla ES modules, **no build step**. `index.html`, `style.css`, `js/*.js`.
- `clients/extension` (MV3), `clients/email-worker` (Cloudflare). `deploy/unraid/` template.

Everything runs in **one process**: the feed scheduler, PageWorker and MailWorker are asyncio tasks started in
`main.py`'s lifespan. Never run several workers.

## Conventions

**Backend**
- Domain errors (`InvalidInput`, `NotFound`, `Conflict`) are raised from repositories/services; the web layer maps
  them to 400/404/409 and a `{"error", "detail"}` body. Error messages are written for the person using the app.
- **Schema changes:** append a new string to `MIGRATIONS` in `app/db/migrations.py`; never edit an old one. Bump
  the expected version in `tests/test_migrations.py`. Migrations run automatically on start, on users' real data.
- **API field names are a contract.** Stash endpoints use camelCase and ISO-8601 strings; feeds and articles use
  snake_case and Unix seconds. That inconsistency is historical and clients depend on it — don't rename fields.
- **An endpoint that schedules asyncio work must be `async def`.** FastAPI runs sync endpoints in a threadpool,
  where `asyncio.create_task` fails with "no running event loop".
- Blocking work (SQLite, trafilatura, imaplib) goes through `run_in_threadpool` / `asyncio.to_thread`.
- Don't reuse one `Response` object across requests: middleware mutates headers on every response.
- Settings are pydantic-settings in `app/settings.py`, validated at startup; add new env vars to
  `tests/unit/test_settings.py`'s `ENV_KEYS`, `.env.example`, the README table and the unRAID template.
- Secrets: API tokens are stored as SHA-256 hashes; the mailbox password is encrypted with `SecretBox`, keyed from
  `SECRET_KEY`. Never log either.

**Security model**
- Non-GET browser requests need `X-Requested-With: reader` (CSRF). Requests carrying `Authorization: Bearer …` or
  `Authorization: GoogleLogin auth=…` are exempt — browsers never send those on their own — as is the Reader API's
  `/accounts/ClientLogin`. If you add another credential scheme, extend `app/web/security.py`.
- Content-Security-Policy is `script-src 'self'`: **no inline `<script>`** anywhere (the theme is set before first
  paint by `static/js/theme-boot.js` for this reason).
- Feed HTML is sanitized on the server and again in the browser; stash text is always rendered as text.

**Frontend**
- Escape every interpolated string with `esc()` from `util.js`. Handlers are delegated from panel roots.
- `<html>` carries `data-mode`, `data-scheme` and `data-density`, so a delegated `closest('[data-scheme]')` matches
  every click on the page. Scope attribute selectors (e.g. `.swatch[data-scheme]`).
- Menus: `openMenu(items, anchor)` in `menus.js` remembers the anchor so the click that opens a menu doesn't close
  it. Use it for any new menu button.
- Themes are full palettes of CSS custom properties per scheme × light/dark in `style.css`, not accent swaps.
- UI copy is short, plain, second person. Explanations span the page with their buttons underneath.

**General**
- Don't use common dev ports (3000, 5000, 8000, 8080). FeedStash is 8672.
- Never add names or importers for the scrapped predecessor apps. Generic imports (OPML, bookmark HTML, Feedly
  export folders) are fine.
- Commit messages: a subject that says what changed for a person (releases end with the version, e.g. `(0.4.0)`),
  a body that says why, and the trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Testing

On macOS, with Python 3.13 (the Docker image's version):

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                                     # unit + API tests
READER_E2E_BROWSER="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" pytest   # + browser tests
```

- **The suite is black-box.** Each API test starts a real uvicorn server on a free port with a fresh database
  (`start_server(**env)` in `tests/conftest.py`). A shared local HTTP server serves generated feeds and pages
  (`tests/support/feedgen.py`); `tests/support/oidc.py` is a fake OIDC provider. `PAGE_CAPTURE` is off by default in
  tests — page tests turn it on and fetch from the local feed server.
- `tests/unit/` calls layers directly, mostly against an in-memory database (`conn`, `user_id` fixtures).
- `tests/e2e/` drives headless Chrome over CDP (`tests/e2e/cdp.py`). The `reader` fixture **fails the test on any
  JavaScript error**, which is how module-cycle and CSP mistakes get caught. `window.reader` exposes app internals
  (`reader.api`, `reader.pollForNew`, `reader.setPref`) for tests.
- The full run takes 5–8 minutes (~235 tests). There's no JS unit runner; for a quick syntax check, copy a module to
  a `.mjs` file and run `node --check` on it.
- Run the full suite before every release. Don't run it while a Docker build is going on the same machine — the
  parallel servers plus the build can exhaust local sockets.

## Releasing

`main` is the release branch. A release:

1. Full test run, including browser tests.
2. Commit and push `main`.
3. `git tag -a vX.Y.Z -m "…"` and `git push origin vX.Y.Z`.
4. `gh run watch` on the Docker workflow — it runs the tests, builds an image, smoke-tests it (starts, drops root,
   serves the setup page), then pushes `linux/amd64` + `linux/arm64` to Docker Hub as `liftbridgelabs/feedstash`
   with tags `X.Y.Z`, `X.Y`, `latest` and `sha-…`.
5. Confirm: `docker buildx imagetools inspect liftbridgelabs/feedstash:X.Y.Z` lists both platforms.

Versioning: patch for fixes and polish, minor for a new capability. The tag becomes `FEEDSTASH_VERSION`, shown in
the sidebar and `/api/health`. Mention schema changes in the release so people take a backup
(`docker exec feedstash python -m app.cli backup /data/backups/feedstash-$(date +%F).db`).

## Traps we've already hit

- **Reverse proxies with their own sign-in** (Pangolin, Authentik, Authelia, Cloudflare Access) answer API calls
  with a 302 to a login page. Anything following redirects sees HTTP 200 and HTML. Clients must treat a redirect or
  a non-JSON reply as an error. Features that make FeedStash reach *out* (IMAP polling) avoid the problem entirely.
- **Some sites block server fetches** (Akamai TLS fingerprinting — headers and HTTP/2 don't help). Don't fight it;
  the browser extension sends the page it can see as `pageHtml`.
- **Error text is stored when an attempt happens**, so old items keep old wording until retried.
- The Cloudflare email worker can be deployed without a CLI by pasting a single minified esbuild bundle into the
  dashboard editor (`npx esbuild src/index.js --bundle --format=esm --minify`). Large pastes of the unminified
  bundle get truncated.
