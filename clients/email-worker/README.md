# FeedStash Email Worker

Forward an email to a dedicated address on your domain and it becomes a note in FeedStash. Subject-line hashtags become tags; the first image attachment (if any) gets attached to the note.

Example: emailing `note@yourdomain.com` with subject `Check this out #reading #ml` and a screenshot attached creates an item titled "Check this out", tagged `reading` + `ml`, with the screenshot attached.

## Prerequisites

- Your domain's DNS is on Cloudflare (Email Routing requires this).
- A Cloudflare account with Workers enabled (free tier is enough for personal volume).
- `npm install -g wrangler` (or use `npx wrangler` throughout instead).

## Setup

1. `cd email-worker && npm install`
2. Edit `wrangler.toml` — set `FEEDSTASH_API_BASE` to your actual FeedStash URL.
3. Mint a dedicated API token for this worker (don't reuse another client's token):
   ```
   curl -X POST https://notes.yourdomain.com/api/tokens \
     -H "Authorization: Bearer <any-existing-token>" \
     -H "Content-Type: application/json" \
     -d '{"clientName":"email-worker"}'
   ```
4. Log in to Wrangler: `npx wrangler login`
5. Deploy: `npx wrangler deploy`
6. Set the secret token (not stored in wrangler.toml, kept out of source control):
   ```
   npx wrangler secret put FEEDSTASH_API_TOKEN
   ```
   Paste the token from step 3 when prompted.

## Wire it up to Email Routing

1. Cloudflare dashboard → your domain → **Email** → **Email Routing**. Enable it if you haven't (Cloudflare walks you through the MX/TXT records automatically since your DNS is already there).
2. Under **Routing rules**, create a new rule:
   - Custom address: e.g. `note@yourdomain.com` (pick whatever address you want to forward notes to)
   - Action: **Send to a Worker**
   - Destination: `feedstash-email-worker` (the worker you just deployed)
3. Save. Send yourself a test email to that address with a subject like `Test note #testing` and check the Review tab in FeedStash — it should show up within a few seconds.

## Debugging

`npx wrangler tail` streams live logs from the worker — run it, send a test email, and watch for the `console.error` output if something fails (bad token, unreachable API, malformed email, etc.).

## Limits

Cloudflare Email Routing caps incoming messages at 25MB. Large image attachments beyond that won't reach the worker at all — email itself has practical limits here regardless.
