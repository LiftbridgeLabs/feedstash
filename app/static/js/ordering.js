/* Manual ordering of folders and feeds. Changes apply locally first so drags feel instant. */

import { afterMove } from './actions.js';
import { api } from './api.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { renderOrganize } from './organize.js';
import { loadTree, renderNav } from './sidebar.js';
import { feedById, feedIdsIn, state } from './state.js';
import { byName } from './util.js';

function rerender() {
  renderNav();
  if (state.route.scope === 'organize') renderOrganize();
}

export async function reorderFolders(ids) {
  const rank = new Map(ids.map((id, i) => [id, i]));
  state.tree.folders.sort((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity));
  rerender();
  try {
    await api('POST', '/api/folders/reorder', { ids });
    return true;
  } catch (err) {
    toast(err.message, { error: true });
    await loadTree();
    return false;
  }
}

/** Sets the order of one folder's feeds (null = Uncategorized); listed feeds from other folders move in. */
export async function reorderFeeds(folderId, ids) {
  const moved = ids.some((id) => (feedById(id)?.folder_id ?? null) !== folderId);
  const rest = feedIdsIn(folderId).filter((id) => !ids.includes(id));
  [...ids, ...rest].forEach((id, position) => {
    const feed = feedById(id);
    if (feed) Object.assign(feed, { folder_id: folderId, position });
  });
  state.tree.feeds.sort((a, b) => a.position - b.position);
  rerender();
  try {
    await api('POST', '/api/feeds/reorder', { folder_id: folderId, ids });
    if (moved) await afterMove();
    return true;
  } catch (err) {
    toast(err.message, { error: true });
    await loadTree();
    return false;
  }
}

function swapped(ids, id, delta) {
  const i = ids.indexOf(id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= ids.length) return null;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  return ids;
}

export function moveFolderBy(id, delta) {
  const ids = swapped(state.tree.folders.map((f) => f.id), id, delta);
  if (ids) reorderFolders(ids);
}

export function moveFeedBy(id, delta) {
  const folderId = feedById(id)?.folder_id ?? null;
  const ids = swapped(feedIdsIn(folderId), id, delta);
  if (ids) reorderFeeds(folderId, ids);
}

export function sortFoldersAlpha() {
  reorderFolders([...state.tree.folders].sort((a, b) => byName(a.name, b.name)).map((f) => f.id));
}

export function sortFeedsAlpha(folderId) {
  const ids = state.tree.feeds
    .filter((f) => (f.folder_id ?? null) === folderId)
    .sort((a, b) => byName(a.title, b.title))
    .map((f) => f.id);
  reorderFeeds(folderId, ids);
}

/** Up/down arrow buttons for the Organize tables. */
export function orderButtons(kind, id, index, count) {
  return `<button class="icon-btn" data-org="${kind}-up" data-id="${id}" title="Move up" ${index <= 0 ? 'disabled' : ''}>${icon('chevron-up')}</button>`
    + `<button class="icon-btn" data-org="${kind}-down" data-id="${id}" title="Move down" ${index >= count - 1 ? 'disabled' : ''}>${icon('chevron-down')}</button>`;
}
