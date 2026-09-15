# FeedStash

Everything you want to read, in one self-hosted app: the feeds you follow, and the links, snippets, screenshots and emails you save from anywhere. It runs as one Docker container and keeps everything in SQLite. Sign in with a password, Google, or any OpenID Connect provider. The browser extension and email worker live in `clients/`; the Android and iOS apps are a separate project.

## Features

**Feeds**
- **Folders and feeds.** Follow a site or feed URL (the feed is found automatically). Rename, move, reorder by drag and drop, unfollow.
- **Mark as read.** Everything, or only articles older than 12 hours, 1 day or 1 week, with Undo. Articles are also marked read as they scroll off the top of the list (can be turned off).
- **Auto-refresh.** Feeds are fetched in the background; new articles appear on their own, or behind a "↑ N new articles" button while you're reading.
- **OPML import and export**, e.g. from Feedly.

**Stash**
- **Capture from anywhere.** The browser extension, forwarding an email, the share sheet on Android and iOS, or **+ Add → Save something** in the web app (you can paste an image straight into it). One note can hold several labeled links.
- **Review.** New items land in the **Inbox**. Mark them reviewed, archive, edit, tag, search, or filter by type and tag.
- **Save articles.** "Save to stash" on any feed article (or press `b`).
- **Import saved links** from Feedly boards, browser bookmarks, Pocket or Raindrop, choosing for each file where its links go and how they're tagged.

**Accounts.** Several people can share one server; each has their own feeds and stash. Admins add and remove accounts in **Settings → Accounts**. Each person also chooses how long their read articles are kept (**Settings → Your account**, 30 days by default; Read later is never deleted).

**Keyboard:** `j`/`k` next/previous article, `o` open, `v` open original, `m` toggle read, `s` read later, `b` save to stash, `c` capture, `r` refresh, `Shift+A` mark all read, `Esc` close.

## Quick start

```bash
docker run -d --name feedstash --restart unless-stopped \
  -p 8672:8672 \
  -e BASE_URL=http://localhost:8672 \
  -v feedstash-data:/data \
  liftbridgelabs/feedstash:latest
```

Open http://localhost:8672 and create the first account; it becomes the admin. Until the image is published on Docker Hub, build it first from this folder with `docker build -t liftbridgelabs/feedstash .`

With Docker Compose instead:

```bash
cp .env.example .env        # set BASE_URL, and sign-in options if you want them
docker compose up -d --build
```

Everything FeedStash stores lives in `/data`: the database (`feedstash.db`), uploaded images (`uploads/`) and the generated session key (`secret.key`).

## Signing in

Turn on any combination. The sign-in page shows whatever is configured.

### Passwords (on by default)

On a fresh install the first visit shows **Create the first account**. That account is an admin and can add more accounts, set their passwords, and make other admins under **Settings → Accounts**. Everyone can change their own password in Settings.

- Create the first account right after starting a new server: until someone does, anyone who can open the page can.
- If `ALLOWED_EMAILS` or `ALLOWED_DOMAINS` is set, the first account must use one of those addresses.
- After 10 wrong passwords for one account (or 30 from one address) within 15 minutes, sign-in is paused for that account or address.
- Set `PASSWORD_LOGIN=false` if you only want Google or OIDC.

Locked out? Reset a password from the server:

```bash
docker exec -it feedstash python -m app.cli set-password --email you@example.com
```

### Google

1. In [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials), set up the OAuth consent screen (External; add yourself as a test user; "Testing" is fine for personal use).
2. **Create credentials → OAuth client ID → Web application**, with the authorized redirect URI `<BASE_URL>/auth/google/callback`. Google only accepts `https` addresses (and `localhost`), so use your https one; Google sign-in won't work on a plain `http://192.168.x.x` address.
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `ALLOWED_EMAILS` (or `ALLOWED_DOMAINS` for a Workspace domain).

### Any OpenID Connect provider

Create an OAuth2/OIDC client (confidential, authorization code flow) with the redirect URI `<BASE_URL>/auth/oidc/callback` (add one for each address in `BASE_URL`) and the scopes `openid email profile`, then set:

| Variable | Example |
|---|---|
| `OIDC_ISSUER` | Authentik: `https://auth.example.com/application/o/feedstash/` · Authelia: `https://auth.example.com` · Keycloak: `https://sso.example.com/realms/home` · Pocket ID: `https://id.example.com` |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | From the provider |
| `OIDC_NAME` | Button text: "Sign in with **Pocket ID**" |
| `ALLOWED_EMAILS` | Who may sign in; `*` lets in anyone your provider allows |

Google and OIDC sign-ins need an email in `ALLOWED_EMAILS`/`ALLOWED_DOMAINS`. If someone already has a password account, signing in with Google or OIDC under the same (verified) email opens that same account. An admin can also give a Google or OIDC account a password in Settings.

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `BASE_URL` | `http://localhost:8672` | The address you open FeedStash at, or several separated by commas (e.g. `https://feedstash.example.com,http://192.168.1.50:8672` for away and at home). Google/OIDC sign-in returns to whichever one you used; the first is the main address. Session cookies are `Secure` whenever you're on https. |
| `PASSWORD_LOGIN` | `true` | Password accounts and first-run setup. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | | Google sign-in. |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | | OpenID Connect sign-in. |
| `OIDC_NAME`, `OIDC_SCOPES` | `single sign-on`, `openid email profile` | Button label and requested scopes. |
| `ALLOWED_EMAILS`, `ALLOWED_DOMAINS` | | Comma-separated. Who may sign in with Google or OIDC. |
| `PUID`, `PGID` | `1000`, `1000` | The user and group the app runs as. The container makes `/data` theirs on start. |
| `PORT` | `8672` | Port inside the container. |
| `FORWARDED_ALLOW_IPS` | `*` | Addresses whose `X-Forwarded-*` headers are trusted. Set it to your proxy's IP if the port is also reachable directly. |
| `SECRET_KEY` | generated | Signs session cookies. Generated once into `/data/secret.key` when empty. |
| `SESSION_DAYS` | `30` | How long you stay signed in. |
| `REFRESH_INTERVAL_MINUTES` | `15` | How often feeds are fetched (5 or more). |
| `RETENTION_DAYS` | `90` | Feed articles older than this are deleted, read or not; Read later and the newest 50 per feed are kept. Read articles can go sooner: each account sets its own limit in Settings (30 days after reading by default). Stash items are never deleted automatically. |
| `DEV_LOGIN` | `false` | Local testing only: skips sign-in entirely. |

## Deploying

The image runs on amd64 and arm64. It starts as root just long enough to give `/data` to `PUID:PGID` (only when the owner is wrong), then runs the app as that user.

### unRAID

Use the template in `deploy/unraid/feedstash.xml`: copy it to `/boot/config/plugins/dockerMan/templates-user/my-feedstash.xml`, then **Docker → Add Container** and pick **feedstash**. Or add the container by hand:

| Field | Value |
|---|---|
| Repository | `liftbridgelabs/feedstash:latest` |
| Port | container `8672` → any free host port |
| Path | container `/data` → `/mnt/cache/appdata/feedstash` |
| Variables | `BASE_URL`, `PUID=99`, `PGID=100`, plus any sign-in settings |

Point `/data` at a pool (`/mnt/cache/...`), not `/mnt/user/...`: SQLite doesn't do well on the `/mnt/user` FUSE layer, and make sure the mover doesn't move the appdata share. To update: **Docker → feedstash → Force update**.

### Synology and other NAS

In **Container Manager → Project**, create a project from this compose file, change the volume to a folder such as `/volume1/docker/feedstash:/data`, and set `PUID`/`PGID` to the owner of that folder (run `id your-user` over SSH; on Synology the group is usually `100`).

### A Linux server behind a reverse proxy

```bash
cp .env.example .env    # BASE_URL=https://feedstash.example.com
docker compose up -d
```

Point the proxy at port 8672. Caddy:

```
feedstash.example.com {
    reverse_proxy localhost:8672
}
```

With Nginx Proxy Manager, add a proxy host for the container's IP and port 8672 and request a certificate; websockets aren't needed. If the container's port is published to the internet as well, bind it to localhost (`127.0.0.1:8672:8672`) or set `FORWARDED_ALLOW_IPS` to the proxy's address.

To use FeedStash both through the proxy and directly at home, list both addresses, the proxy's first: `BASE_URL=https://feedstash.example.com,http://192.168.1.50:8672`. You stay signed in on each, and the cookie is `Secure` on the https one. (Pointing the domain at the proxy from inside your network too, with local DNS, gives you one https address everywhere, which Google sign-in needs.)

### Windows and macOS

Install Docker Desktop and use the compose file as above. Keep the named volume (`feedstash-data`) rather than a Windows folder for `/data`: SQLite is much happier on it.

### Backups and updates

Back up while it runs:

```bash
docker exec feedstash python -m app.cli backup /data/backups/feedstash-$(date +%F).db
```

Then copy `/data/backups/` and `/data/uploads/` somewhere safe. Or stop the container and copy the whole `/data` folder.

To update, pull the new image and recreate the container (`docker compose pull && docker compose up -d`, or Force update on unRAID). Database changes are applied automatically on start; take a backup first.

Other admin commands: `create-account`, `set-password`, `list-accounts` (`docker exec feedstash python -m app.cli --help`).

## Moving from Feedly

Download your data from Feedly and unzip it. The archive has:

- **`subscriptions.opml`**: your feeds and folders. In FeedStash, open **Organize feeds** and import it.
- **`my boards/`**: one HTML file per board. In FeedStash, open **Settings → Import saved links**, choose the files, and decide for each board whether it's imported, whether its links land in the Inbox, Everything saved or the Archive, and what they're tagged. Original save dates are kept, and links you already have are skipped.
- **`my boards/board-Unsaved-bookmarks.html`** (links you removed from Feedly) and **`read/`** (every article you opened, titles only). The import leaves these unticked if you choose them; you rarely want them.

The same import works for bookmarks exported from Chrome, Firefox, Edge or Safari, and for Pocket and Raindrop exports.

## Connecting the extension, email worker and phone apps

Each client signs in with its own API token, so you can revoke one without affecting the others.

1. In the web app, open **Settings → Connected apps** and click **New token**. Copy the token; it's shown only once (only a hash is stored).
2. Configure the client with your `BASE_URL` and that token:
   - **Browser extension** (`clients/extension/`): load it unpacked, then set the server URL and token in its options.
   - **Email worker** (`clients/email-worker/`): set `FEEDSTASH_API_BASE` and `FEEDSTASH_API_TOKEN` for the Cloudflare Worker.
   - **Android / iOS apps**: enter the server URL and token in the app's Settings tab.

See the extension's and email worker's READMEs for install steps. None of the clients has been built and tried against FeedStash yet.

## Client API

The clients use these endpoints (camelCase fields, `{"error": "..."}` on failures):

- `POST /api/items` (JSON or multipart; `type`, `title`, `content`, `url`, `links`, `tags`, `image`, `source`)
- `GET /api/items?type=&tag=&reviewed=&archived=&q=&limit=&offset=`, `GET/PATCH/DELETE /api/items/{id}`
- `GET /api/tags`, `GET /api/health`
- `GET/POST /api/tokens`, `DELETE /api/tokens/{id}`
- `GET /uploads/{name}`

Every item has a `links` list of `{id, url, label}`, and `url` mirrors the first link, so clients that only know one URL keep working. `links` can be sent as a list of URLs or `{url, label}` objects, as a JSON string of either (for multipart), or one URL per line. `PATCH` with `links` replaces the whole list; `PATCH` with only `url` swaps the first link and keeps the rest.

API tokens can't manage accounts; that needs a signed-in browser session.

## Publishing the image

`.github/workflows/docker-publish.yml` runs the tests, builds the image, checks that it starts, drops root and serves the setup page, then pushes `linux/amd64` and `linux/arm64` builds to Docker Hub as `liftbridgelabs/feedstash`. It runs when you push a version tag, or by hand from the Actions tab.

1. Push this repository to GitHub.
2. Add the repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access token with read and write access).
3. Tag a release: `git tag v0.1.0 && git push origin v0.1.0`. That publishes `0.1.0`, `0.1` and `latest`.

To use another image name, change `IMAGE` in the workflow, `image:` in `docker-compose.yml`, and the unRAID template.

## How it's built

Dependencies point one way: `web` → `services` → `feeds` → `db`. Lower layers never import higher ones.

```
app/
  __main__.py        python -m app: runs the server with host/port from the settings
  main.py            create_app(): wires settings, database, image store, scheduler, middleware and routers
  settings.py        typed, validated configuration (pydantic-settings)
  cli.py             admin commands: accounts, passwords, backups
  passwords.py       scrypt password hashing
  errors.py          domain errors (InvalidInput, NotFound, Conflict); the web layer maps them to 400/404/409
  images.py          uploaded images: validated by content, random names
  opml.py            OPML parse/build, pure functions

  db/
    database.py      connections; one transaction per unit of work
    migrations.py    versioned schema changes, tracked in PRAGMA user_version
    models.py        plain dataclasses returned by the repositories
    repositories/    all SQL lives here: users, folders, feeds, articles, items, tokens

  feeds/             parser (no I/O), fetcher (HTTP only), ingest (storage), scheduler (background refresh)

  services/
    accounts.py      first-run setup, checking passwords, admin changes to accounts
    bookmarks.py     importing saved links in bulk
    subscriptions.py following a feed, importing OPML
    stash.py         capturing items, saving feed articles to the stash

  web/
    api/             JSON routers: tree, articles, folders, feeds, opml, imports, stash, tokens, accounts
    auth.py          sign-in (passwords, Google, OIDC), API tokens, allowlist
    ratelimit.py     pauses password guessing
    ...

  static/            the single-page UI (plain JavaScript modules, no build step)

clients/             browser extension and email worker
deploy/unraid/       unRAID container template
docker-entrypoint.sh fixes /data ownership, then runs the app as PUID:PGID
```

The background refresher runs inside the web process, so run a single process (the Docker image does).

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                           # unit tests + API tests
READER_E2E_BROWSER="/path/to/chrome" pytest      # also run the browser tests (Chrome or Edge)
```

- `tests/unit/`: each layer directly (settings, parser, fetcher, migrations, repositories, passwords, accounts, images).
- `tests/test_*.py`: the real server on a free port with a fresh database. `test_auth.py` covers setup, passwords, lockout, accounts and a full OIDC sign-in against a local test provider; `test_client_compat.py` sends requests shaped exactly like the extension, email worker and phone apps.
- `tests/e2e/`: a headless browser (first-run setup, scroll-to-mark-read, drag and drop, auto-refresh, capturing and reviewing).

**Security notes**

- Passwords are hashed with scrypt. Sessions are signed cookies (`SameSite=Lax`, `Secure` over https), started fresh on every sign-in.
- Feed HTML is sanitized twice (server and browser), and a strict Content-Security-Policy blocks all scripts except the app's own. Stash text is always shown as plain text.
- Browser requests need a CSRF header; API clients use bearer tokens, which browsers never send on their own.
- Uploaded image URLs are not behind sign-in, so the random file name is what protects them. SVG and other non-image uploads are rejected.
- Any signed-in user can make the server fetch any http(s) URL when adding a feed. Only give accounts to people you trust.
