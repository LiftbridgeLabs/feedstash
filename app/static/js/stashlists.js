/* Stash folders (where saved items live) and smart lists (saved searches), both shown in the sidebar. */

import { api } from './api.js';
import { modal, promptDialog, toast } from './dialogs.js';
import { navigate } from './router.js';
import { loadTree } from './sidebar.js';
import { folderOptionsHTML, TYPE_LABELS } from './stash.js';
import { ITEM_TYPES, smartListById, stashFolderById, state, stashViewRef } from './state.js';
import { esc, plural } from './util.js';

/* ---- folders */

export async function newStashFolder() {
  const name = await promptDialog({
    title: 'New stash folder',
    label: 'Folder name',
    confirmText: 'Create',
    onSubmit: (value) => api('POST', '/api/stash/folders', { name: value }),
  });
  if (!name) return;
  await loadTree();
  toast(`Created “${name}”. Drag saved items onto it, or pick it when you save something.`);
}

export async function renameStashFolder(id) {
  const folder = stashFolderById(id);
  if (!folder) return;
  const name = await promptDialog({
    title: 'Rename stash folder',
    label: 'Folder name',
    value: folder.name,
    onSubmit: (value) => api('PATCH', `/api/stash/folders/${id}`, { name: value }),
  });
  if (name) await loadTree();
}

export async function deleteStashFolder(id) {
  const folder = stashFolderById(id);
  if (!folder) return;
  const ok = await modal({
    title: `Delete “${folder.name}”?`,
    confirmText: 'Delete folder',
    danger: true,
    html: folder.count
      ? `<p>The ${plural(folder.count, 'item')} in it stay in your stash, in no folder.</p>`
      : '<p>This folder is empty.</p>',
    onSubmit: () => api('DELETE', `/api/stash/folders/${id}`),
  });
  if (!ok) return;
  const wasOpen = state.route.scope === 'stash' && state.route.id === `folder:${id}`;
  await loadTree();
  if (wasOpen) navigate('#/stash/all');
  toast('Folder deleted');
}

export async function moveStashFolderBy(id, delta) {
  const ids = (state.stash.summary.folders || []).map((f) => f.id);
  const at = ids.indexOf(id);
  const to = at + delta;
  if (at < 0 || to < 0 || to >= ids.length) return;
  ids.splice(to, 0, ...ids.splice(at, 1));
  try {
    await api('POST', '/api/stash/folders/reorder', { ids });
    await loadTree();
  } catch (err) {
    toast(err.message, { error: true });
  }
}

/* ---- smart lists */

function listFormHTML(values) {
  const typeOptions = ITEM_TYPES
    .map((type) => `<option value="${type}" ${type === values.type ? 'selected' : ''}>${TYPE_LABELS[type]}</option>`)
    .join('');
  return `
    <label>Name<input type="text" name="name" value="${esc(values.name || '')}" maxlength="200" autocomplete="off"
      data-1p-ignore data-lpignore="true" data-form-type="other"></label>
    <label><span>Words <small>(optional; searches notes, links, tags and saved pages)</small></span>
      <input type="text" name="query" value="${esc(values.query || '')}" maxlength="500" autocomplete="off"></label>
    <label>Kind<select name="type"><option value="">Anything</option>${typeOptions}</select></label>
    <label>Tag <small>(optional)</small><input type="text" name="tag" value="${esc(values.tag || '')}" maxlength="50" autocomplete="off"></label>
    <label>Folder<select name="folderId">${folderOptionsHTML(values.folderId || null)}</select></label>`;
}

function listFromForm(fd) {
  return {
    name: (fd.get('name') || '').trim(),
    query: (fd.get('query') || '').trim() || null,
    type: fd.get('type') || null,
    tag: (fd.get('tag') || '').trim() || null,
    folderId: fd.get('folderId') ? Number(fd.get('folderId')) : null,
  };
}

/** Saves what's on screen now (the search, and any type, tag or folder filter) as a smart list. */
export async function saveCurrentAsSmartList() {
  const view = state.route.id;
  const ref = stashViewRef(view);
  const values = {
    name: state.stash.query || (view.startsWith('tag:') ? `#${view.slice(4)}` : '') || TYPE_LABELS[view] || '',
    query: state.stash.query,
    type: ITEM_TYPES.includes(view) ? view : '',
    tag: view.startsWith('tag:') ? view.slice(4) : '',
    folderId: ref.kind === 'folder' ? ref.id : null,
  };
  const created = await modal({
    title: 'Save as smart list',
    confirmText: 'Save',
    html: `<p class="muted">A smart list is a search that stays in your sidebar; it always shows what matches now.</p>
      ${listFormHTML(values)}`,
    onSubmit: (fd) => {
      const body = listFromForm(fd);
      if (!body.name) throw new Error('Give the smart list a name');
      return api('POST', '/api/stash/lists', body);
    },
  });
  if (!created || created === true) return;
  await loadTree();
  navigate(`#/stash/list/${created.id}`);
  toast(`Saved “${created.name}”`);
}

export async function editSmartList(id) {
  const list = smartListById(id);
  if (!list) return;
  const updated = await modal({
    title: 'Edit smart list',
    confirmText: 'Save',
    html: listFormHTML(list),
    onSubmit: (fd) => {
      const body = listFromForm(fd);
      if (!body.name) throw new Error('Give the smart list a name');
      return api('PATCH', `/api/stash/lists/${id}`, body);
    },
  });
  if (!updated || updated === true) return;
  await loadTree();
  if (state.route.scope === 'stash' && state.route.id === `list:${id}`) navigate(`#/stash/list/${id}`);
}

export async function deleteSmartList(id) {
  const list = smartListById(id);
  if (!list) return;
  const ok = await modal({
    title: `Delete “${list.name}”?`,
    confirmText: 'Delete',
    danger: true,
    html: '<p>Only the saved search goes; the items it finds stay in your stash.</p>',
    onSubmit: () => api('DELETE', `/api/stash/lists/${id}`),
  });
  if (!ok) return;
  const wasOpen = state.route.scope === 'stash' && state.route.id === `list:${id}`;
  await loadTree();
  if (wasOpen) navigate('#/stash/all');
  toast('Smart list deleted');
}
