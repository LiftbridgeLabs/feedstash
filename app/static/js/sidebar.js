/* The sidebar: folders and feeds with unread counts, collapsing, and drag-and-drop ordering. */

import { moveFeed, newFolder } from './actions.js';
import { api } from './api.js';
import { icon } from './icons.js';
import { closeMenus, openContextMenu } from './menus.js';
import { reorderFeeds, reorderFolders } from './ordering.js';
import { navigate } from './router.js';
import { captureDialog, ITEM_DRAG, moveItemToFolder } from './stash.js';
import { newStashFolder } from './stashlists.js';
import {
  els, feedById, feedIdsIn, scopeTitle, stashFolderById, STASH_VIEWS, state, stashViewRef, sumUnread, unreadFor,
} from './state.js';
import { $, $$, esc, favicon, saveJSON } from './util.js';

/** Loads everything the sidebar shows: feeds and folders, plus stash counts and tags. */
export async function loadTree() {
  const [tree, summary, tags] = await Promise.all([
    api('GET', '/api/tree'), api('GET', '/api/stash/summary'), api('GET', '/api/tags'),
  ]);
  state.tree = tree;
  state.stash.summary = summary;
  state.stash.tags = tags;
  renderNav();
  renderHeader();
}

let navTimer = null;
/** Coalesces bursts of count changes (e.g. while scroll-marking) into one render. */
export function scheduleNavRender() {
  if (navTimer) return;
  navTimer = setTimeout(() => {
    navTimer = null;
    renderNav();
    renderHeader();
  }, 120);
}

export function renderNav() {
  const { folders, feeds } = state.tree;
  const { scope, id } = state.route;
  const active = (s, i = null) => (scope === s && id === i ? 'active' : '');
  const count = (n) => (n ? `<span class="nav-count">${n > 999 ? '999+' : n}</span>` : '');

  const feedRow = (f) => `
    <div class="nav-row ${active('feed', f.id)} ${f.unread ? '' : 'zero'}" role="link" tabindex="0"
         data-href="#/feed/${f.id}" data-feed="${f.id}" draggable="true">
      <span class="nav-icon"><img src="${esc(favicon(f))}" alt="" loading="lazy"></span>
      <span class="nav-label">${esc(f.title)}</span>
      ${f.last_error ? `<span class="warn" title="${esc(f.last_error)}">${icon('alert')}</span>` : ''}
      ${count(f.unread)}
      <button class="icon-btn more" data-menu="feed" data-id="${f.id}" title="Feed options">${icon('more')}</button>
    </div>`;

  const folderBlock = (folder, list) => {
    const key = folder ? `f${folder.id}` : 'uncategorized';
    const href = folder ? `#/folder/${folder.id}` : '#/uncategorized';
    const isActive = folder ? active('folder', folder.id) : active('uncategorized');
    return `
      <div class="folder ${state.collapsed.has(key) ? 'collapsed' : ''}" ${folder ? `data-folder-id="${folder.id}"` : ''}>
        <div class="nav-row ${isActive}" role="link" tabindex="0" data-href="${href}" data-drop="${folder ? folder.id : 'none'}"
             ${folder ? `draggable="true" data-folder-drag="${folder.id}"` : ''}>
          <span class="chevron" data-collapse="${key}" title="Expand/collapse">${icon('chevron-down')}</span>
          <span class="nav-label">${esc(folder ? folder.name : 'Uncategorized')}</span>
          ${count(sumUnread(list))}
          ${folder ? `<button class="icon-btn more" data-menu="folder" data-id="${folder.id}" title="Folder options">${icon('more')}</button>` : ''}
        </div>
        <div class="folder-feeds">${list.map(feedRow).join('') || '<div class="nav-empty">Empty folder — drag feeds here</div>'}</div>
      </div>`;
  };

  let html = `
    <div class="nav-section"><span>Feeds</span>
      <button class="icon-btn" data-action="new-folder" title="New folder">${icon('plus')}</button>
    </div>
    <div class="nav-row ${active('all')}" role="link" tabindex="0" data-href="#/all">
      <span class="nav-icon">${icon('rss')}</span><span class="nav-label">All articles</span>${count(sumUnread(feeds))}
    </div>
    <div class="nav-row ${active('starred')}" role="link" tabindex="0" data-href="#/starred">
      <span class="nav-icon">${icon('bookmark')}</span><span class="nav-label">Read later</span>${count(state.tree.starred_count)}
    </div>`;

  for (const folder of folders) html += folderBlock(folder, feeds.filter((f) => f.folder_id === folder.id));
  const uncategorized = feeds.filter((f) => f.folder_id == null);
  if (uncategorized.length) html += folderBlock(null, uncategorized);
  if (!feeds.length && !folders.length) {
    html += `<div class="nav-empty">You're not following anything yet. Use <b>+ Add → Follow a feed</b>, or bring
      feeds in from Feedly or an OPML file under <a href="#/settings">Settings</a>.</div>`;
  }

  const stash = state.stash.summary;
  // Type and tag views are filters inside the stash, so "Everything saved" stays highlighted for them; a folder
  // or smart list is a place of its own.
  const elsewhere = stashViewRef(id).kind !== null;
  const stashActive = (view) => (scope === 'stash'
    && (id === view || (view === 'all' && !elsewhere && id !== 'inbox' && id !== 'archived')) ? 'active' : '');
  const stashRow = (view, iconName, n) => `
    <div class="nav-row ${stashActive(view)} ${n ? '' : 'zero'}" role="link" tabindex="0" data-href="#/stash/${view}">
      <span class="nav-icon">${icon(iconName)}</span><span class="nav-label">${esc(STASH_VIEWS[view])}</span>${count(n)}
    </div>`;
  const stashFolderRow = (folder) => `
    <div class="nav-row ${stashActive(`folder:${folder.id}`)} ${folder.count ? '' : 'zero'}" role="link" tabindex="0"
         data-href="#/stash/folder/${folder.id}" data-stash-folder="${folder.id}">
      <span class="nav-icon">${icon('folder')}</span><span class="nav-label">${esc(folder.name)}</span>${count(folder.count)}
      <button class="icon-btn more" data-menu="stash-folder" data-id="${folder.id}" title="Folder options">${icon('more')}</button>
    </div>`;
  const smartListRow = (list) => `
    <div class="nav-row ${stashActive(`list:${list.id}`)}" role="link" tabindex="0" data-href="#/stash/list/${list.id}">
      <span class="nav-icon">${icon('search')}</span><span class="nav-label">${esc(list.name)}</span>
      <button class="icon-btn more" data-menu="smart-list" data-id="${list.id}" title="Smart list options">${icon('more')}</button>
    </div>`;
  html += `
    <div class="nav-section"><span>Stash</span>
      <button class="icon-btn" data-action="new-stash-folder" title="New stash folder">${icon('folder')}</button>
      <button class="icon-btn" data-action="capture" title="Save something (c)">${icon('plus')}</button>
    </div>
    ${stashRow('inbox', 'inbox', stash.inbox)}
    ${stashRow('all', 'layers', stash.total)}
    ${stashRow('archived', 'archive', stash.archived)}
    ${(stash.folders || []).map(stashFolderRow).join('')}
    ${(stash.lists || []).map(smartListRow).join('')}`;

  els.nav.innerHTML = html;
  $('[data-route="organize"]').classList.toggle('active', scope === 'organize');
  $('[data-route="settings"]').classList.toggle('active', scope === 'settings');
}

export function renderHeader() {
  const { scope, id } = state.route;
  const title = scopeTitle(scope, id);
  els.title.textContent = title;
  const total = sumUnread(state.tree.feeds);
  document.title = `${total ? `(${total}) ` : ''}${title} · FeedStash`;
  els.count.textContent = headerCount(scope, id);
}

function headerCount(scope, id) {
  if (scope === 'organize' || scope === 'settings') return '';
  if (scope === 'stash') {
    const { summary } = state.stash;
    if (id === 'inbox') return `${summary.inbox} to review`;
    if (id === 'archived') return `${summary.archived} archived`;
    if (id === 'all') return `${summary.total} saved`;
    const ref = stashViewRef(id);
    if (ref.kind === 'folder') return `${stashFolderById(ref.id)?.count ?? 0} saved`;
    if (ref.kind === 'list') return 'Smart list';
    return summary.by_type[id] != null ? `${summary.by_type[id]} saved` : '';
  }
  const n = unreadFor(scope, id);
  return scope === 'starred' ? `${n} saved` : `${n} unread`;
}

function toggleCollapse(key) {
  if (state.collapsed.has(key)) state.collapsed.delete(key);
  else state.collapsed.add(key);
  saveJSON('reader.collapsed', [...state.collapsed]);
  renderNav();
}

export function wireNav() {
  els.nav.addEventListener('click', (e) => {
    const collapse = e.target.closest('[data-collapse]');
    if (collapse) return toggleCollapse(collapse.dataset.collapse);
    const more = e.target.closest('[data-menu]');
    if (more) return openContextMenu(more.dataset.menu, Number(more.dataset.id), more);
    if (e.target.closest('[data-action="new-folder"]')) return newFolder();
    if (e.target.closest('[data-action="new-stash-folder"]')) return newStashFolder();
    if (e.target.closest('[data-action="capture"]')) return captureDialog();
    if (e.target.closest('a[href]')) return;
    const row = e.target.closest('[data-href]');
    if (row) navigate(row.dataset.href);
  });
  els.nav.addEventListener('keydown', (e) => {
    const row = e.target.closest('[data-href]');
    if (row && e.target === row && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      navigate(row.dataset.href);
    }
  });
  wireDragAndDrop();
  wireItemDrop();
}

/* Dragging a saved item from the stash onto a folder in the sidebar files it there. Registered after the nav's
   own drag handling, which clears drop marks for drags it doesn't recognize. */
function wireItemDrop() {
  const target = (e) => (e.dataTransfer.types.includes(ITEM_DRAG) ? e.target.closest('[data-stash-folder]') : null);
  els.nav.addEventListener('dragover', (e) => {
    const row = target(e);
    if (!row) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    row.classList.add('drop-target');
  });
  els.nav.addEventListener('dragleave', (e) => target(e)?.classList.remove('drop-target'));
  els.nav.addEventListener('drop', (e) => {
    const row = target(e);
    if (!row) return;
    e.preventDefault();
    row.classList.remove('drop-target');
    moveItemToFolder(Number(e.dataTransfer.getData(ITEM_DRAG)), Number(row.dataset.stashFolder));
  });
}

/* Drag and drop: reorder folders, reorder feeds, or drop a feed on a folder header to move it there. */
function wireDragAndDrop() {
  let drag = null; // { kind: 'feed' | 'folder', id }
  const clearDrop = () => $$('.drop-target, .drop-before, .drop-after', els.nav)
    .forEach((x) => x.classList.remove('drop-target', 'drop-before', 'drop-after'));
  const half = (el, e) => {
    const r = el.getBoundingClientRect();
    return e.clientY < r.top + r.height / 2 ? 'before' : 'after';
  };
  const dropSpot = (e) => {
    if (!drag) return null;
    if (drag.kind === 'folder') {
      const block = e.target.closest('.folder[data-folder-id]');
      if (!block || Number(block.dataset.folderId) === drag.id) return null;
      return { el: block, mode: half(block, e), folderId: Number(block.dataset.folderId) };
    }
    const row = e.target.closest('[data-feed]');
    if (row) {
      if (Number(row.dataset.feed) === drag.id) return null;
      return { el: row, mode: half(row, e), feedId: Number(row.dataset.feed) };
    }
    const header = e.target.closest('[data-drop]') || e.target.closest('.folder')?.querySelector('[data-drop]');
    if (!header) return null;
    return { el: header, mode: 'into', folderId: header.dataset.drop === 'none' ? null : Number(header.dataset.drop) };
  };

  els.nav.addEventListener('dragstart', (e) => {
    const feedRow = e.target.closest('[data-feed]');
    const folderRow = e.target.closest('[data-folder-drag]');
    if (feedRow) drag = { kind: 'feed', id: Number(feedRow.dataset.feed) };
    else if (folderRow) drag = { kind: 'folder', id: Number(folderRow.dataset.folderDrag) };
    else return;
    closeMenus();
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', ''); // Firefox won't start a drag without data
  });
  els.nav.addEventListener('dragover', (e) => {
    const spot = dropSpot(e);
    clearDrop();
    if (!spot) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    spot.el.classList.add(spot.mode === 'into' ? 'drop-target' : `drop-${spot.mode}`);
  });
  els.nav.addEventListener('dragleave', (e) => {
    if (!els.nav.contains(e.relatedTarget)) clearDrop();
  });
  els.nav.addEventListener('dragend', () => {
    drag = null;
    clearDrop();
  });
  els.nav.addEventListener('drop', (e) => {
    const spot = dropSpot(e);
    clearDrop();
    if (!spot) return;
    e.preventDefault();
    const { kind, id } = drag;
    drag = null;
    if (kind === 'folder') {
      const ids = state.tree.folders.map((f) => f.id).filter((x) => x !== id);
      ids.splice(ids.indexOf(spot.folderId) + (spot.mode === 'after' ? 1 : 0), 0, id);
      reorderFolders(ids);
    } else if (spot.mode === 'into') {
      if ((feedById(id)?.folder_id ?? null) !== spot.folderId) moveFeed(id, spot.folderId);
    } else {
      const folderId = feedById(spot.feedId)?.folder_id ?? null;
      const ids = feedIdsIn(folderId).filter((x) => x !== id);
      ids.splice(ids.indexOf(spot.feedId) + (spot.mode === 'after' ? 1 : 0), 0, id);
      reorderFeeds(folderId, ids);
    }
  });
}
