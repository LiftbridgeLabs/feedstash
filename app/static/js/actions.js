/* User actions that change data: marking scopes read, refreshing, and managing folders and feeds. */

import { api } from './api.js';
import { flushMarks, renderListEnd, resetList } from './articles.js';
import { modal, promptDialog, toast } from './dialogs.js';
import { renderOrganize } from './organize.js';
import { reorderFeeds } from './ordering.js';
import { applyRoute, navigate } from './router.js';
import { loadTree } from './sidebar.js';
import { feedById, feedIdsIn, feedsInScope, folderById, state } from './state.js';
import { $, esc, hoursLabel, plural } from './util.js';

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
      <label>Website or feed URL
        <input type="text" name="url" required placeholder="https://example.com" autocomplete="off" inputmode="url" spellcheck="false">
      </label>
      <label>Folder<select name="folder">${folderOptions(defaultFolder, { allowNew: true })}</select></label>
      <label data-new-folder hidden>New folder name<input type="text" name="folder_name" maxlength="200" autocomplete="off"></label>
      <label>Name (optional)<input type="text" name="title" maxlength="200" autocomplete="off" placeholder="Uses the feed's own title"></label>`,
    onOpen: wireFolderSelect,
    onSubmit: async (fd) => {
      const url = (fd.get('url') || '').trim();
      if (!url) throw new Error('Enter a website or feed URL');
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
  toast(`Following ${feed.title}`);
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
