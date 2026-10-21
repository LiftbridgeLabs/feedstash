# Changelog

What changed in each FeedStash release, newest first. Before you update, check **Before you update** for anything
to do first, like taking a backup. Admins see the rest of a release's notes in FeedStash after updating.

## 0.9.0

### New
- **Set up Google or single sign-on in Settings.** Admins can now add Google, or any sign-in that speaks OpenID
  Connect (Pocket ID, Authentik, Authelia, Keycloak and more), under Settings → Admin → Sign-in, no server settings or
  restart needed. The form shows the address to give your provider and checks it when you save. You can add more
  than one, turn one off or remove it. Each one either leaves who gets in to your provider (like a user group in
  Pocket ID), or only lets in the addresses and domains on FeedStash's allowed list; Google always uses the list,
  since anyone can have a Google account. Providers already set in the server's settings keep working and show up
  in the list.
- **Try it before anyone sees it.** Each sign-in has a Try it button that runs a real sign-in in a new tab and
  tells you whether it worked and whether that person would be let in, without signing you out. It works while
  the button is still hidden.
- **Your own sign-in buttons.** Give each one an icon, built in or your provider's own logo, and a color, with a
  preview while you choose. One switch hides every sign-in button at once, handy while testing.
- **A tidier Settings:** settings is now split into the following groups: You, Feeds, Stash, Apps, and Admin, with
  each section in its own box. They appear as a menu on the left, or tabs on a phone. Organize feeds has a way back
  to Settings.
- **Set up the browser extension and the email worker without GitHub.** Settings → Apps has both as downloads, with
  step-by-step instructions, and Email to your stash explains both ways to send email in.
- **See which feeds went quiet.** Organize feeds now shows when each feed last brought in something new, and
  calls out feeds with nothing new for a month, so one that stopped publishing or moved doesn't go unnoticed.

### Fixes
- Feeds with an old `http://` address that a site refuses, like PhoneArena's, now load. FeedStash tries the
  `https://` address instead and updates the feed to it once it works. Importing an OPML or Feedly export that
  still lists the `http://` address doesn't add the feed a second time.

### Before you update
- As always, it's recommended to create a backup before updating. This release adds to the database, and once
  it has run, older versions of FeedStash won't start on that database, so a backup is how you'd go back.

## 0.8.1

### Fixes
- Feeds that some sites turned away with HTTP 403 load again. FeedStash now introduces itself to sites as a feed
  reader, not as a browser, which bot protection like Cloudflare's lets through.
- Fewer "too many requests" (HTTP 429) errors. Feeds from the same site are now fetched one after another, not
  all at once, and when a site asks FeedStash to slow down, it leaves that site alone for a while.

## 0.8.0

### New
- Logs you control. FeedStash now keeps its own log files in its data folder and starts a new one when a file
  gets too big. Admins pick how detailed the log is, which requests get a line, how big a file gets and how many
  to keep under Settings → Logs, and can read the latest lines or download the whole log there.
- Quieter logs. Out of the box only saves, edits, failures and feed refreshes are logged, and the container's own
  log only gets warnings and errors, so it stays small without any Docker settings.

### Fixes
- The unread list opens faster when you have thousands of unread articles.
- Importing a big bookmarks file no longer holds up feed refreshes and saves while it runs.

### Settings
- New: `LOG_REQUESTS`, `changes` by default: which requests are logged until an admin changes it in Settings →
  Logs. `errors` logs only failures, `all` logs every request like before, `none` logs no requests.

### Before you update
- As always, it's recommended to create a backup before updating. This release adds to the database.

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
