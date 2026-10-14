# Changelog

What changed in each FeedStash release, newest first. Admins see the entries for the releases they haven't seen yet
when they first open FeedStash after an update. Before updating, look under **Action needed**: it says when to take
a backup or change a setting.

## Unreleased

### New
- **Settings → Tags:** check several tags and merge them into one, or rename one. Tags that look alike (#vibe and
  #vibes) are grouped so you can check them in one click. The tag row in the Edit and Save dialogs ends with a
  **Manage tags** chip that opens it.
- Admins see what changed after an update, and the version in the sidebar says when a newer release is out.

### Fixed
- The scrollbar under the tag row no longer covers the tags.
- Editing a saved item is checked against its owner in the database as well as in the app.

### Settings
- `SETUP_TOKEN`: once it's set, the setup page asks for it from every network, your own included. It's only needed
  until the first account exists, so you can remove it after setup.
- `UPDATE_CHECK` (new, on by default): once a day, while an admin has FeedStash open, the server asks GitHub for
  the latest release so the sidebar can say when there's an update. Nothing is sent but the request itself. Set it
  to `false` to turn this off.

### Action needed
- **Take a backup first:** this release changes the database (it remembers which release notes each admin has
  seen).
- **If you run the Cloudflare email worker,** build and deploy it again (`clients/email-worker`). A sender address
  with no `@` could match a one-letter `ALLOWED_SENDERS` entry; now it never matches.

## 0.6.1

### New
- A folder's or feed's own menu marks it read by age: older than 12 hours, a day or a week, not only everything.

## 0.6.0

### New
- See your existing tags while tagging: a row of your tags with counts, **All tags**, and a nudge when a new tag
  looks like one you have (#vibes → #vibe).
- Rename or merge a tag from its menu. Smart lists and stash rules that use it follow along.
