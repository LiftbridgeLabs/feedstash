# Changelog

What changed in each FeedStash release, newest first. Before you update, check **Before you update** for anything
to do first, like taking a backup. Admins see the rest of a release's notes in FeedStash after updating.

## 0.7.0

### New
- Grid view for the stash. Show any folder, smart list or tag as a list, a Pinterest-style grid or tiles, with the
  switch at the top right. Cards show the picture or the link's preview, the title, tags and the start of your
  notes. Each view remembers its own choice.
- Several pictures per item. Save a few screenshots together, and add or remove pictures when you edit an item.
  The first one shows on the card.
- Changed from Links, Notes, Screenshot to just one save form. The three were pretty much crossing over in usage.
  Now you can add a title, notes, links, pictures and tags in one place, and FeedStash works out what it is: just
  a link is a Link, just pictures a Screenshot, anything else a Note.
- Snippets are now called Notes. Nothing changes in what they do.
- No more Inbox since it was just a repeat of "Everything saved". The stash now opens on Everything saved. When
  you're done with something, archive it or delete it.
- Use only the feeds or only the stash. Settings → Your account → Use hides the half you don't need. Nothing is
  deleted, so you can switch back any time.
- Add an "About FeedStash" section in Settings, only shows for admins: including the version, whether an update
  is out, and where to suggest a feature, report a problem or get help.

### Before you update
- As always, it's recommended to create a backup before updating. This release adds to the database.

## 0.6.2

### New
- **Manage your tags in one place.** Settings → Tags lists every tag in use. You can now merge tags into one or
  rename them. If you have #code, #codes and #coding, you can merge them into a single tag.
- **Update notices for admins.** After an update you'll see what's new, and the version at the bottom of the
  sidebar tells you when a newer release is out.

### Settings
- `SETUP_TOKEN` is now asked for on every network once you set it, your own included. You only need it until your
  account exists, so you can remove it afterwards.
- New: `UPDATE_CHECK`, on by default. Once a day, while an admin is using FeedStash, it asks GitHub whether there's
  a newer release. Set it to `false` to turn that off.

### Before you update
- As always, it's recommended to create a backup before updating. This release adds to the database.

### After you update
- If you use the Cloudflare email worker, deploy it again from `clients/email-worker`. It now turns away sender
  addresses without an @.

## 0.6.1

### New
- **Mark read by age.** A folder's or feed's menu can now mark articles older than 12 hours, a day or a week as
  read, not just everything.

## 0.6.0

### New
- **See your tags while you tag.** The tag field shows the tags you already use, with how often, and All tags
  shows the rest. If a new tag looks like one you have (#vibes when you use #vibe), it suggests yours.
- **Rename or merge a tag** from its menu. Smart lists and stash rules that use it are updated too.
