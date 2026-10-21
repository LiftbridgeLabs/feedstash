# FeedStash Capture (browser extension)

Manifest V3 extension for Chrome/Edge/Brave (Chromium-based). Right-click a link, selection, or page to save it; or click the toolbar icon for a quick-capture popup with a live screenshot option.

## Load it (unpacked, for personal use — no store listing needed)

The easiest way to get it is from FeedStash itself: **Settings → Apps → Browser extension → Download the extension**,
then unzip it. (From a checkout of this repository, use this `extension/` folder instead.)

1. Go to `chrome://extensions` (`edge://extensions` in Edge)
2. Enable "Developer mode" (top right)
3. Click "Load unpacked" and select the unzipped `feedstash-extension` folder
4. Click the new toolbar icon → "Settings" (or right-click the icon → Options)
5. Enter your server URL (e.g. `https://notes.yourdomain.com`) and an API token

Make a dedicated token for the extension in the web app, under **Settings → Connected apps → New token**, so you can
revoke it on its own later. (Tokens can only be made from a signed-in web session, not with another token.)

6. Click "Test connection" in the options page to confirm it's wired up.

## What it does

- Right-click a link → "Save link to FeedStash"
- Select text, right-click → "Save selection to FeedStash" (saved as a snippet)
- Right-click anywhere on a page → "Save this page to FeedStash" (link) or "Save screenshot to FeedStash" (captures the visible tab as a PNG)
- When you save the page you're on, the extension also sends the page itself, so FeedStash keeps a readable copy even of sites that turn servers away or need you to be signed in. Pages the browser won't let extensions read are saved as a plain link, and the server fetches them itself.
- Toolbar icon → popup with type switcher (link/snippet/screenshot), tags field, and a save button — prefilled with the current tab's URL/title

A green badge flash on the toolbar icon means success; red means it failed (check the background service worker console at `chrome://extensions` → FeedStash Capture → "service worker" link for the error).

## Notes

- Firefox reads the same files with a slightly different manifest (background scripts instead of a service worker,
  and an add-on id). FeedStash builds it for you: **Download for Firefox** in Settings → Apps.
- The only site the extension can reach on its own is your FeedStash server, which it asks you to allow when you
  click **Save** or **Test connection** in its Settings. It reads the page you're saving with the one-time access a
  browser gives when you click its toolbar button or one of its right-click items, so it never asks for access to
  every website.
