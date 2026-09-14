/* The sidebar: folders and feeds with unread counts, collapsing, and drag-and-drop ordering. */

import { moveFeed, newFolder } from './actions.js';
import { api } from './api.js';
import { icon } from './icons.js';
import { closeMenus, openContextMenu } from './menus.js';
import { reorderFeeds, reorderFolders } from './ordering.js';
import { navigate } from './router.js';
import { els, feedById, feedIdsIn, scopeTitle, state, sumUnread, unreadFor } from './state.js';
import { $, $$, esc, favicon, saveJSON } from './util.js';

export async function loadTree() {
  state.tree = await api('GET', '/api/tree');
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
    <div class="nav-row ${active('all')}" role="link" tabindex="0" data-href="#/all">
      <span class="nav-icon">${icon('inbox')}</span><span class="nav-label">All</span>${count(sumUnread(feeds))}
    </div>
    <div class="nav-row ${active('starred')}" role="link" tabindex="0" data-href="#/starred">
      <span class="nav-icon">${icon('bookmark')}</span><span class="nav-label">Read later</span>${count(state.tree.starred_count)}
    </div>
    <div class="nav-section"><span>Feeds</span>
      <button class="icon-btn" data-action="new-folder" title="New folder">${icon('plus')}</button>
    </div>`;

  if (!feeds.length && !folders.length) {
    html += `<div class="nav-empty">You're not following anything yet. Use <b>+ Follow</b>, or import an OPML
      file from <a href="#/organize">Organize feeds</a>.</div>`;
  }
  for (const folder of folders) html += folderBlock(folder, feeds.filter((f) => f.folder_id === folder.id));
  const uncategorized = feeds.filter((f) => f.folder_id == null);
  if (uncategorized.length) html += folderBlock(null, uncategorized);

  els.nav.innerHTML = html;
  $('[data-route="organize"]').classList.toggle('active', scope === 'organize');
}

export function renderHeader() {
  const { scope, id } = state.route;
  const title = scopeTitle(scope, id);
  els.title.textContent = title;
  const total = sumUnread(state.tree.feeds);
  document.title = `${total ? `(${total}) ` : ''}${title} · Reader`;
  $('#list-actions').hidden = scope === 'organize';
  if (scope === 'organize') {
    els.count.textContent = '';
  } else {
    const n = unreadFor(scope, id);
    els.count.textContent = scope === 'starred' ? `${n} saved` : `${n} unread`;
  }
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
