# FeedStash Email Worker

Forward an email to an address on your own domain and it lands in your stash. Subject hashtags become tags, links in the message are saved as the item's links (so FeedStash fetches a preview and keeps a readable copy), and the first image attachment is attached.

Example: emailing `stash@yourdomain.com` with the subject `Check this out #reading #ml` creates an item titled "Check this out", tagged `reading` and `ml`, with whatever the message linked to.

## What you need

- **A domain whose DNS is on Cloudflare.** Cloudflare Email Routing only works there.
- **A FeedStash the worker can reach from the internet** — a Cloudflare Worker can't see a LAN address. If FeedStash is only on your LAN, put it behind a reverse proxy or a Cloudflare Tunnel first, and use that address as `FEEDSTASH_API_BASE`.
- A Cloudflare account with Workers (the free plan is plenty) and Node installed for `npx wrangler`.

## Set it up

1. **Make a token:** in FeedStash, **Settings → Connected apps → New token**, name it `email-worker`, and copy it. It's shown only once.
2. **Point the worker at your server:** edit `wrangler.toml` and set `FEEDSTASH_API_BASE` to your FeedStash address and `ALLOWED_SENDERS` to the address(es) you'll send from. Anyone not on that list is bounced, so leaving it empty means anyone who learns the address can write into your stash.
3. **Install and deploy:**
   ```bash
   cd clients/email-worker
   npm install
   npx wrangler login
   npx wrangler deploy
   ```
4. **Give it the token:**
   ```bash
   npx wrangler secret put FEEDSTASH_API_TOKEN
   ```
   Paste the token from step 1 when prompted.

## Wire up the address

1. Cloudflare dashboard → your domain → **Email → Email Routing**. Enable it if it isn't already; Cloudflare adds the MX and TXT records for you.
2. Under **Routing rules**, add a rule:
   - **Custom address:** `stash@yourdomain.com` (whatever you want to forward to)
   - **Action:** Send to a Worker
   - **Destination:** `feedstash-email-worker`
3. Send a test email to that address with a subject like `Test note #testing`. It should appear in your Inbox in FeedStash within a few seconds.

## When something goes wrong

`npx wrangler tail` streams the worker's logs — run it, send a test, and watch. The worker bounces mail it couldn't save, so a failure comes back to you as a delivery error rather than disappearing:

- **HTTP 401** — the token is wrong or was revoked. Make a new one and `wrangler secret put` it again.
- **A network or 5xx error** — the worker can't reach `FEEDSTASH_API_BASE` from the internet.
- **"only accepts mail from its owner"** — the sender isn't in `ALLOWED_SENDERS`.

Stash rules (**Settings → Stash rules**) run on everything that arrives this way, so you can tag mail from a given domain, file it in a folder, or send it straight past the Inbox.

## Limits

Cloudflare Email Routing caps incoming messages at 25 MB, so very large attachments never reach the worker.
