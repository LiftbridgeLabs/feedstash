/* The Organize feeds page: tables for renaming, moving, ordering and unfollowing, plus OPML. */

import { addFeedDialog, deleteFolder, folderOptions, newFolder, unfollowFeed } from './actions.js';
import { api } from './api.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { moveFeedBy, moveFolderBy, orderButtons, sortFoldersAlpha } from './ordering.js';
import { loadTree } from './sidebar.js';
import { els, feedIdsIn, state, sumUnread } from './state.js';
import { $, $$, agoLong, esc, favicon, plural } from './util.js';

/** The router has already switched to the organize panel. */
export function showOrganize() {
  renderOrganize();
}

export function renderOrganize() {
  const { folders, feeds } = state.tree;
  const folderRows = folders.map((f, i) => {
    const inFolder = feeds.filter((x) => x.folder_id === f.id);
    return `<tr>
      <td class="order">${orderButtons('folder', f.id, i, folders.length)}</td>
      <td><input type="text" value="${esc(f.name)}" data-folder-name="${f.id}" aria-label="Folder name" maxlength="200"></td>
      <td class="num">${inFolder.length}</td>
      <td class="num">${sumUnread(inFolder)}</td>
      <td class="row-actions"><button class="icon-btn" data-org="delete-folder" data-id="${f.id}" title="Delete folder">${icon('trash')}</button></td>
    </tr>`;
  }).join('');

  // Same order as the sidebar: by folder, then by position within the folder.
  const folderRank = new Map(folders.map((f, i) => [f.id, i]));
  const rank = (f) => (f.folder_id == null ? folders.length : folderRank.get(f.folder_id));
  const orderedFeeds = [...feeds].sort((a, b) => rank(a) - rank(b) || a.position - b.position);
  const feedRows = orderedFeeds.map((f) => {
    const siblings = feedIdsIn(f.folder_id ?? null);
    const status = f.last_error
      ? `<span class="status-err" title="${esc(f.last_error)}">${esc(f.last_error.slice(0, 60))}</span>`
      : f.last_fetched_at ? `<span class="muted">Updated ${agoLong(f.last_fetched_at)}</span>` : '<span class="muted">Waiting for first fetch</span>';
    return `<tr data-search="${esc(`${f.title} ${f.url}`.toLowerCase())}">
      <td class="order">${orderButtons('feed', f.id, siblings.indexOf(f.id), siblings.length)}</td>
      <td><div class="feed-cell"><img src="${esc(favicon(f))}" alt="" loading="lazy">
        <div class="grow"><input type="text" value="${esc(f.title)}" data-feed-title="${f.id}" aria-label="Feed name" maxlength="200">
        <div class="url" title="${esc(f.url)}">${esc(f.url)}</div></div></div></td>
      <td><select data-feed-folder="${f.id}" aria-label="Folder">${folderOptions(f.folder_id)}</select></td>
      <td>${status}</td>
      <td class="num">${f.unread}</td>
      <td class="row-actions"><button class="btn btn-sm" data-org="unfollow" data-id="${f.id}">Unfollow</button></td>
    </tr>`;
  }).join('');

  els.organize.innerHTML = `
    <div class="org-head">
      <p class="muted">Moving from Feedly? Download your OPML from <b>feedly.com/i/opml</b>, then import it here.
        Names save when you leave the field. Reorder with the arrows, or drag folders and feeds in the sidebar.</p>
      <div class="org-actions">
        <button class="btn btn-sm" data-org="add-feed">${icon('plus')}Follow feed</button>
        <button class="btn btn-sm" data-org="new-folder">${icon('folder')}New folder</button>
        ${folders.length > 1 ? '<button class="btn btn-sm" data-org="sort-folders">Sort folders A–Z</button>' : ''}
        <button class="btn btn-sm" data-org="import">Import OPML</button>
        <a class="btn btn-sm" href="/api/opml/export" download>Export OPML</a>
        <input type="file" accept=".opml,.xml,text/xml,application/xml,text/x-opml" data-org-file hidden>
      </div>
    </div>

    <h3>Folders (${folders.length})</h3>
    ${folders.length ? `<div class="table-wrap"><table class="org-table">
      <thead><tr><th></th><th>Name</th><th class="num">Feeds</th><th class="num">Unread</th><th></th></tr></thead>
      <tbody>${folderRows}</tbody></table></div>` : '<p class="muted">No folders yet.</p>'}

    <h3>Feeds (${feeds.length})</h3>
    ${feeds.length ? `<input type="search" class="org-filter" placeholder="Filter feeds…" value="${esc(state.orgFilter)}" data-org-filter>
      <div class="table-wrap"><table class="org-table">
      <thead><tr><th></th><th>Name</th><th>Folder</th><th>Status</th><th class="num">Unread</th><th></th></tr></thead>
      <tbody data-feed-rows>${feedRows}</tbody></table></div>` : '<p class="muted">No feeds yet.</p>'}`;
  applyOrgFilter();
}

function applyOrgFilter() {
  const q = state.orgFilter.trim().toLowerCase();
  $$('[data-feed-rows] tr', els.organize).forEach((row) => {
    row.hidden = Boolean(q) && !row.dataset.search.includes(q);
  });
}

async function importOpml(file) {
  const fd = new FormData();
  fd.append('file', file);
  toast('Importing…', { duration: 30000 });
  try {
    const res = await api('POST', '/api/opml/import', fd);
    const parts = [`Imported ${plural(res.added, 'feed')}`];
    if (res.folders_created) parts.push(`into ${plural(res.folders_created, 'new folder')}`);
    let msg = parts.join(' ');
    if (res.skipped) msg += ` (${res.skipped} already followed or invalid)`;
    toast(`${msg}. Fetching articles in the background…`, { duration: 8000 });
    await loadTree();
    if (state.route.scope === 'organize') renderOrganize();
    // Poll a few times while the server fetches the new feeds.
    for (let i = 0; i < 8 && res.added; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      await loadTree();
      if (state.route.scope === 'organize' && !els.organize.contains(document.activeElement)) renderOrganize();
    }
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireOrganize() {
  const org = els.organize;
  org.addEventListener('click', (e) => {
    const button = e.target.closest('[data-org]');
    if (!button) return;
    const id = Number(button.dataset.id);
    switch (button.dataset.org) {
      case 'add-feed': addFeedDialog(); break;
      case 'new-folder': newFolder(); break;
      case 'import': $('[data-org-file]', org).click(); break;
      case 'delete-folder': deleteFolder(id); break;
      case 'unfollow': unfollowFeed(id); break;
      case 'folder-up': moveFolderBy(id, -1); break;
      case 'folder-down': moveFolderBy(id, 1); break;
      case 'feed-up': moveFeedBy(id, -1); break;
      case 'feed-down': moveFeedBy(id, 1); break;
      case 'sort-folders': sortFoldersAlpha(); break;
    }
  });

  org.addEventListener('input', (e) => {
    if (e.target.matches('[data-org-filter]')) {
      state.orgFilter = e.target.value;
      applyOrgFilter();
    }
  });

  org.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches('input[type=text]')) e.target.blur();
    if (e.key === 'Escape' && e.target.matches('input[type=text]')) {
      e.target.value = e.target.defaultValue;
      e.target.blur();
    }
  });

  org.addEventListener('change', async (e) => {
    const t = e.target;
    try {
      if (t.matches('[data-org-file]')) {
        if (t.files[0]) await importOpml(t.files[0]);
        t.value = '';
      } else if (t.matches('[data-folder-name]')) {
        const name = t.value.trim();
        if (!name || name === t.defaultValue) { t.value = t.defaultValue; return; }
        await api('PATCH', `/api/folders/${t.dataset.folderName}`, { name });
        await loadTree();
        renderOrganize();
        toast('Folder renamed');
      } else if (t.matches('[data-feed-title]')) {
        const title = t.value.trim();
        if (!title || title === t.defaultValue) { t.value = t.defaultValue; return; }
        await api('PATCH', `/api/feeds/${t.dataset.feedTitle}`, { title });
        t.defaultValue = title;
        await loadTree();
        toast('Feed renamed');
      } else if (t.matches('[data-feed-folder]')) {
        await api('PATCH', `/api/feeds/${t.dataset.feedFolder}`, { folder_id: t.value ? Number(t.value) : null });
        await loadTree();
        renderOrganize();
        toast('Feed moved');
      }
    } catch (err) {
      if ('defaultValue' in t && t.type === 'text') t.value = t.defaultValue;
      toast(err.message, { error: true });
      if (t.matches('select')) renderOrganize();
    }
  });
}
