/* User actions that change data: marking scopes read, refreshing, and managing folders and feeds. */

import { api } from './api.js';
import { flushMarks, renderListEnd, resetList } from './articles.js';
import { modal, promptDialog, toast } from './dialogs.js';
import { renderOrganize } from './organize.js';
import { reorderFeeds } from './ordering.js';
import { applyRoute, navigate } from './router.js';
import { loadTree } from './sidebar.js';
import { feedById, feedIdsIn, feedsInScope, folderById, state } from './state.js';
import { $, $$, agoLong, esc, hoursLabel, plural } from './util.js';

/* ---- marking read & refreshing */

function viewOverlaps(scope, id) {
  const cur = state.route;
  if (cur.scope === 'all' || cur.scope === 'starred' || (cur.scope === scope && cur.id === id)) return true;
  const curFeeds = new Set(feedsInScope(cur.scope, cur.id).map((f) => f.id));
  return feedsInScope(scope, id).some((f) => curFeeds.has(f.id));
}

export async function markScope(scope, id, olderThanHours) {
  await flushMarks();
  const body = { scope, id, older_than_hours: olderThanHours };
  const isCurrentView = scope === state.route.scope && id === state.route.id;
  // "Mark all" only covers what was loaded when you opened the view, not articles that arrived since.
  if (!olderThanHours && isCurrentView && state.list.maxId != null) body.max_id = state.list.maxId;
  const reload = async () => {
    const overlaps = viewOverlaps(scope, id);
    await loadTree();
    if (overlaps && state.route.scope !== 'organize') resetList();
  };
  try {
    const res = await api('POST', '/api/mark-read', body);
    await reload();
    if (!res.marked) {
      toast(olderThanHours ? `No unread articles older than ${hoursLabel(olderThanHours)}` : 'Nothing to mark as read');
      return;
    }
    const suffix = olderThanHours ? ` older than ${hoursLabel(olderThanHours)}` : '';
    toast(`Marked ${plural(res.marked, 'article')}${suffix} as read`, {
      action: 'Undo',
      onAction: async () => {
        const undo = await api('POST', '/api/mark-read/undo', { scope, id, batch: res.batch });
        await reload();
        toast(`Restored ${plural(undo.restored, 'article')}`);
      },
    });
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export async function refresh(scope = state.route.scope, id = state.route.id) {
  const button = $('#refresh-btn');
  if (button.classList.contains('spin')) return;
  button.classList.add('spin');
  try {
    await flushMarks();
    const res = await api('POST', '/api/refresh', { scope: scope === 'organize' ? 'all' : scope, id });
    await loadTree();
    if (state.route.scope === 'organize') renderOrganize();
    else if (res.new) resetList();
    else renderListEnd();
    toast(res.new ? `${plural(res.new, 'new article')}` : 'No new articles');
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    button.classList.remove('spin');
  }
}

/* ---- after changes */

/** Structural changes (delete, unfollow) may invalidate the current view. */
export async function afterStructureChange() {
  await loadTree();
  applyRoute();
}

/** Moving a feed only changes what folder and Uncategorized views contain. */
export async function afterMove() {
  await loadTree();
  if (['folder', 'uncategorized'].includes(state.route.scope)) applyRoute();
  else if (state.route.scope === 'organize') renderOrganize();
}

/* ---- folders */

export async function newFolder() {
  const name = await promptDialog({
    title: 'New folder',
    label: 'Folder name',
    confirmText: 'Create',
    onSubmit: (value) => api('POST', '/api/folders', { name: value }),
  });
  if (!name) return;
  await loadTree();
  if (state.route.scope === 'organize') renderOrganize();
  toast(`Created folder “${name}”. Drag feeds onto it to fill it.`);
}

export async function renameFolder(id) {
  const folder = folderById(id);
  if (!folder) return;
  const name = await promptDialog({
    title: 'Rename folder',
    label: 'Folder name',
    value: folder.name,
    onSubmit: (value) => api('PATCH', `/api/folders/${id}`, { name: value }),
  });
  if (!name) return;
  await loadTree();
  if (state.route.scope === 'organize') renderOrganize();
}

export async function deleteFolder(id) {
  const folder = folderById(id);
  if (!folder) return;
  const count = state.tree.feeds.filter((f) => f.folder_id === id).length;
  const ok = await modal({
    title: `Delete “${folder.name}”?`,
    confirmText: 'Delete folder',
    danger: true,
    html: count
      ? `<p>This folder contains ${plural(count, 'feed')}. They'll move to <b>Uncategorized</b> unless you unfollow them.</p>
         <label class="check"><input type="checkbox" name="unfollow"> Also unfollow ${count === 1 ? 'it' : `all ${count}`}</label>`
      : '<p>This folder is empty.</p>',
    onSubmit: (fd) => api('DELETE', `/api/folders/${id}?unfollow=${fd.get('unfollow') ? 'true' : 'false'}`),
  });
  if (ok) await afterStructureChange();
}

export function folderOptions(selected, { allowNew = false } = {}) {
  const opts = state.tree.folders
    .map((f) => `<option value="${f.id}" ${String(f.id) === String(selected ?? '') ? 'selected' : ''}>${esc(f.name)}</option>`)
    .join('');
  return `<option value="" ${selected == null || selected === '' ? 'selected' : ''}>Uncategorized</option>${opts}${allowNew ? '<option value="__new">+ New folder…</option>' : ''}`;
}

function wireFolderSelect(dialog) {
  const select = $('select[name=folder]', dialog);
  const newFolderField = $('[data-new-folder]', dialog);
  select.addEventListener('change', () => {
    newFolderField.hidden = select.value !== '__new';
    if (!newFolderField.hidden) $('input', newFolderField).focus();
  });
}

async function resolveFolder(fd) {
  const value = fd.get('folder');
  if (value !== '__new') return value ? Number(value) : null;
  const name = (fd.get('folder_name') || '').trim();
  if (!name) throw new Error('Enter a name for the new folder');
  const existing = state.tree.folders.find((f) => f.name.toLowerCase() === name.toLowerCase());
  if (existing) return existing.id;
  return (await api('POST', '/api/folders', { name })).id;
}

/* ---- feeds */

export async function addFeedDialog() {
  const { scope, id } = state.route;
  const defaultFolder = scope === 'folder' ? id : scope === 'feed' ? feedById(id)?.folder_id : null;
  const feed = await modal({
    title: 'Follow a feed',
    confirmText: 'Follow',
    busyText: 'Looking for a feed…',
    html: `
      <label>Website, feed URL or subreddit
        <input type="text" name="url" required placeholder="https://example.com or r/selfhosted" autocomplete="off" inputmode="url" spellcheck="false">
      </label>
      <label>Folder<select name="folder">${folderOptions(defaultFolder, { allowNew: true })}</select></label>
      <label data-new-folder hidden>New folder name<input type="text" name="folder_name" maxlength="200" autocomplete="off"></label>
      <label>Name (optional)<input type="text" name="title" maxlength="200" autocomplete="off" placeholder="Uses the feed's own title"></label>`,
    onOpen: wireFolderSelect,
    onSubmit: async (fd) => {
      const url = (fd.get('url') || '').trim();
      if (!url) throw new Error('Enter a website, feed URL or subreddit');
      return api('POST', '/api/feeds', {
        url,
        folder_id: await resolveFolder(fd),
        title: (fd.get('title') || '').trim() || null,
      });
    },
  });
  if (!feed) return;
  await loadTree();
  navigate(`#/feed/${feed.id}`);
  toast(feed.last_error ? `Following ${feed.title}. ${feed.last_error}` : `Following ${feed.title}`);
}

/** Starter packs of feeds (the server's discover.json): follow one feed or a whole pack, each into a folder named
    after its pack. */
export async function discoverDialog() {
  let packs;
  try {
    ({ packs } = await api('GET', '/api/discover'));
  } catch (err) {
    toast(err.message, { error: true });
    return;
  }
  const searchText = (pack, feed) => [feed.title, feed.about, feed.site, pack.name, pack.description].join(' ').toLowerCase();
  const feedRow = (pack, feed) => `<li data-search="${esc(searchText(pack, feed))}">
      <div class="grow"><b>${esc(feed.title)}</b> <span class="muted">· ${esc(feed.cadence)}</span>
        <div class="muted">${esc(feed.about)}</div></div>
      ${feed.followed ? '<span class="muted">Following</span>'
        : `<button type="button" class="btn btn-sm" data-follow-url="${esc(feed.url)}" data-pack="${esc(pack.name)}">Follow</button>`}
    </li>`;
  let followed = 0;
  await modal({
    title: 'Discover feeds',
    confirmText: 'Done',
    html: `<p class="muted">Feeds to start with, in packs. Each one you follow goes into a folder named after its pack.</p>
      <input type="search" data-discover-search placeholder="Search by name or topic, or type an address or r/subreddit"
        aria-label="Search the starter feeds" autocomplete="off" spellcheck="false">
      <div data-discover-other hidden></div>
      ${packs.map((pack) => `<section class="discover-pack">
        <div class="discover-head"><div class="grow"><h3>${esc(pack.name)}</h3><p class="muted">${esc(pack.description)}</p></div>
          ${pack.feeds.some((f) => !f.followed) ? `<button type="button" class="btn btn-sm" data-follow-pack="${esc(pack.id)}">Follow all</button>` : ''}</div>
        <ul>${pack.feeds.map((feed) => feedRow(pack, feed)).join('')}</ul>
      </section>`).join('')}`,
    onOpen: (dialog) => {
      $('[data-cancel]', dialog).hidden = true;
      const search = $('[data-discover-search]', dialog);
      search.addEventListener('keydown', (e) => { if (e.key === 'Enter') e.preventDefault(); });  // not Done
      search.addEventListener('input', () => filterDiscover(dialog, search.value));
      // Under the row's name: why it isn't followed, or why its articles come later.
      const note = (button, text, error) => {
        const row = button.closest('li');
        $('.discover-note', row)?.remove();
        if (text) $('.grow', row).append(Object.assign(document.createElement('div'), {
          className: `discover-note${error ? ' error' : ''}`, textContent: text,
        }));
      };
      const follow = async (button) => {
        button.disabled = true;
        button.textContent = 'Following…';
        note(button, '');
        try {
          const feed = await api('POST', '/api/feeds', { url: button.dataset.followUrl, folder_name: button.dataset.pack });
          if (feed.last_error) note(button, feed.last_error);
          button.replaceWith(Object.assign(document.createElement('span'), { className: 'muted', textContent: 'Following' }));
          followed += 1;
          return true;
        } catch (err) {
          button.disabled = false;
          button.textContent = 'Try again';
          note(button, `Not followed. ${err.message}`, true);
          return false;
        }
      };
      dialog.addEventListener('click', async (e) => {
        const one = e.target.closest('[data-follow-url]');
        if (one) return follow(one);
        const all = e.target.closest('[data-follow-pack]');
        if (!all) return;
        all.disabled = true;
        const done = $('[type=submit]', dialog);
        done.disabled = true;  // so the sidebar is refreshed after the whole pack, not partway through
        // One at a time: each follow checks the feed, and a site shouldn't see a burst from one server.
        for (const button of $$('[data-follow-url]', all.closest('.discover-pack'))) await follow(button);
        done.disabled = false;
        all.remove();
      });
    },
  });
  if (!followed) return;
  await loadTree();
  toast(`Following ${plural(followed, 'new feed')}`);
}

/** Shows the starter feeds matching every word typed, and offers to follow what was typed when it's an address or a
    subreddit (the server turns "r/name" into the subreddit's feed). */
function filterDiscover(dialog, text) {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  let shown = 0;
  for (const pack of $$('.discover-pack', dialog)) {
    let packShown = 0;
    for (const row of $$('li[data-search]', pack)) {
      row.hidden = !words.every((word) => row.dataset.search.includes(word));
      if (!row.hidden) packShown += 1;
    }
    pack.hidden = !packShown;
    const all = $('[data-follow-pack]', pack);
    if (all) all.hidden = words.length > 0;  // "Follow all" would follow the hidden ones too
    shown += packShown;
  }
  const typed = text.trim();
  // The forms the server's app/feeds/reddit.py accepts.
  const subreddit = /^\/?r\/\w{2,21}\/?$/i.test(typed)
    || /^(?:https?:\/\/)?(?:(?:www|old|new|m)\.)?reddit\.com\/r\/\w{2,21}(?:\/\.rss)?\/?(?:\?.*)?$/i.test(typed);
  const address = subreddit || /^(https?:\/\/)?[^\s/]+\.[^\s]+$/i.test(typed);
  const other = $('[data-discover-other]', dialog);
  other.hidden = !address && shown > 0;
  other.innerHTML = address
    ? `<ul><li><div class="grow"><b>${esc(typed)}</b>
        <div class="muted">${subreddit ? 'A subreddit, followed into a Reddit folder' : 'FeedStash looks for its feed'}</div></div>
        <button type="button" class="btn btn-sm" data-follow-url="${esc(typed)}"${subreddit ? ' data-pack="Reddit"' : ''}>Follow</button></li></ul>`
    : '<p class="muted">Nothing in the starter packs matches. Type a website\'s address or r/ and a subreddit\'s name to follow it.</p>';
}

/** How much a feed posts and how much of it you read, starred or saved: for deciding whether to keep it. */
export async function showFeedInfo(id) {
  const feed = feedById(id);
  if (!feed) return;
  let stats;
  try {
    stats = await api('GET', `/api/feeds/${id}/stats`);
  } catch (err) {
    toast(err.message, { error: true });
    return;
  }
  const span = stats.window_days === 28 ? 'the last 4 weeks' : `the last ${plural(stats.window_days, 'day')}`;
  const share = stats.posted ? ` (${Math.round((stats.read / stats.posted) * 100)}%)` : '';
  const link = (url) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`;
  const rows = [
    ['Posts', stats.posted ? `About ${stats.posts_per_week} a week, ${plural(stats.posted, 'article')} in ${span}`
      : `Nothing in ${span}`],
    ['You', stats.posted ? `Read ${stats.read} of them${share} · starred ${stats.starred} · saved ${stats.saved} to your stash`
      : `Saved ${stats.saved} to your stash`],
    ['Last received', feed.last_new_at ? agoLong(feed.last_new_at) : 'Nothing yet'],
    ['Last checked', feed.last_fetched_at ? agoLong(feed.last_fetched_at) : 'Not yet'],
  ];
  if (feed.last_error) rows.push(['Problem', feed.last_error]);
  // Escaped below like the rest; these two are links built here from escaped addresses.
  const links = [['Feed address', link(feed.url)]];
  if (feed.site_url) links.push(['Website', link(feed.site_url)]);
  await modal({
    title: feed.title,
    confirmText: 'Done',
    html: `<dl class="feed-info">${rows.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join('')}${
      links.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${value}</dd>`).join('')}</dl>
      <p class="muted">Read counts include articles you marked read without opening.</p>`,
    onOpen: (dialog) => { $('[data-cancel]', dialog).hidden = true; },
  });
}

export async function renameFeed(id) {
  const feed = feedById(id);
  if (!feed) return;
  const title = await promptDialog({
    title: 'Rename feed',
    label: 'Name',
    value: feed.title,
    onSubmit: (value) => api('PATCH', `/api/feeds/${id}`, { title: value }),
  });
  if (!title) return;
  await loadTree();
  if (state.route.scope === 'organize') renderOrganize();
}

export async function moveFeedDialog(id) {
  const feed = feedById(id);
  if (!feed) return;
  const ok = await modal({
    title: `Move “${feed.title}”`,
    confirmText: 'Move',
    html: `<label>Folder<select name="folder">${folderOptions(feed.folder_id, { allowNew: true })}</select></label>
      <label data-new-folder hidden>New folder name<input type="text" name="folder_name" maxlength="200" autocomplete="off"></label>`,
    onOpen: wireFolderSelect,
    onSubmit: async (fd) => api('PATCH', `/api/feeds/${id}`, { folder_id: await resolveFolder(fd) }),
  });
  if (ok) await afterMove();
}

/** Dropping a feed on a folder puts it at the end of that folder. */
export async function moveFeed(feedId, folderId) {
  const title = feedById(feedId)?.title;
  const folder = folderId == null ? 'Uncategorized' : folderById(folderId)?.name;
  if (await reorderFeeds(folderId, [...feedIdsIn(folderId), feedId])) toast(`Moved “${title}” to ${folder}`);
}

export async function unfollowFeed(id) {
  const feed = feedById(id);
  if (!feed) return;
  const ok = await modal({
    title: `Unfollow “${feed.title}”?`,
    confirmText: 'Unfollow',
    danger: true,
    html: '<p>Its articles will be removed, including any you saved for later.</p>',
    onSubmit: () => api('DELETE', `/api/feeds/${id}`),
  });
  if (ok) await afterStructureChange();
}
