# FeedStash Capture (browser extension)

Manifest V3 extension for Chrome/Edge/Brave (Chromium-based). Right-click a link, selection, or page to save it; or click the toolbar icon for a quick-capture popup with a live screenshot option.

## Load it (unpacked, for personal use — no store listing needed)

1. Go to `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked" and select this `extension/` folder
4. Click the new toolbar icon → "Settings" (or right-click the icon → Options)
5. Enter your server URL (e.g. `https://notes.yourdomain.com`) and an API token

Mint a dedicated token for the extension rather than reusing your web UI token, so you can revoke it independently later:

```
curl -X POST https://notes.yourdomain.com/api/tokens \
  -H "Authorization: Bearer <any-existing-token>" \
  -H "Content-Type: application/json" \
  -d '{"clientName":"extension"}'
```

6. Click "Test connection" in the options page to confirm it's wired up.

## What it does

- Right-click a link → "Save link to FeedStash"
- Select text, right-click → "Save selection to FeedStash" (saved as a snippet)
- Right-click anywhere on a page → "Save this page to FeedStash" (link) or "Save screenshot to FeedStash" (captures the visible tab as a PNG)
- Toolbar icon → popup with type switcher (link/snippet/screenshot), tags field, and a save button — prefilled with the current tab's URL/title

A green badge flash on the toolbar icon means success; red means it failed (check the background service worker console at `chrome://extensions` → FeedStash Capture → "service worker" link for the error).

## Notes

- Firefox: Manifest V3 support differs slightly (background service worker vs. background scripts). This extension targets Chromium; a Firefox port would need `background.scripts` instead of `background.service_worker` in the manifest.
- `host_permissions` is broad (`http://*/*`, `https://*/*`) so it can talk to whatever server URL you configure, since that's your own domain and not known ahead of time. If you publish this to the Chrome Web Store later, Google's review process will flag broad host permissions — for personal sideloading it's not an issue.
