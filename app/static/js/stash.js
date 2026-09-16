/* The stash: links, snippets, screenshots and emails saved from anywhere. New items wait in the Inbox. */

import { api } from './api.js';
import { showNewBanner } from './autorefresh.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { collectLinks, linkRowsHTML, wireLinkRows } from './links.js';
import { navigate } from './router.js';
import { sanitize } from './sanitize.js';
import { renderHeader, renderNav } from './sidebar.js';
import { editSmartList, saveCurrentAsSmartList } from './stashlists.js';
import { els, ITEM_TYPES, smartListById, stashFolderById, STASH_VIEWS, state, stashViewRef } from './state.js';
import { $, $$, ago, esc, fullDate } from './util.js';

const PAGE_SIZE = 50;
/** Drag type for moving a saved item onto a folder in the sidebar. */
export const ITEM_DRAG = 'application/x-feedstash-item';
export const TYPE_LABELS = { link: 'Link', snippet: 'Snippet', screenshot: 'Screenshot', email: 'Email' };
const TYPE_ICONS = { link: 'external', snippet: 'text', screenshot: 'image', email: 'mail' };

const timestamp = (iso) => Math.floor(Date.parse(iso) / 1000);
const httpUrl = (url) => (/^https?:\/\//i.test(url || '') ? url : null);
const firstLine = (text) => (text || '').trim().split('\n')[0].slice(0, 200);
const itemTitle = (item) => item.title || (item.type === 'link' ? '' : firstLine(item.content))
  || item.links[0]?.label || item.preview?.title || item.url || '(untitled)';
const isSaving = (item) => state.tree.page_capture && ['pending', 'working'].includes(item.preview?.status);

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

/* ---- which items a view shows */

function viewQuery(view) {
  const params = new URLSearchParams({ limit: PAGE_SIZE });
  const ref = stashViewRef(view);
  const words = [];
  if (view === 'inbox') params.set('reviewed', 'false');
  else if (view === 'archived') params.set('archived', 'true');
  else if (view.startsWith('tag:')) params.set('tag', view.slice(4));
  else if (ref.kind === 'folder') params.set('folder', ref.id);
  else if (ref.kind === 'list') {
    const list = smartListById(ref.id);
    if (list?.query) words.push(list.query);
    if (list?.type) params.set('type', list.type);
    if (list?.tag) params.set('tag', list.tag);
    if (list?.folderId) params.set('folder', list.folderId);
  } else if (ITEM_TYPES.includes(view)) params.set('type', view);
  if (state.stash.query) words.push(state.stash.query);
  if (words.length) params.set('q', words.join(' '));
  return params;
}

/** The folders to choose from, for the pickers in the dialogs and the open item. */
export function folderOptionsHTML(selected) {
  const options = (state.stash.summary.folders || [])
    .map((f) => `<option value="${f.id}" ${f.id === selected ? 'selected' : ''}>${esc(f.name)}</option>`)
    .join('');
  return `<option value="" ${selected ? '' : 'selected'}>No folder</option>${options}`;
}

/** Whether an item still belongs in the view after a change (reviewing removes it from the Inbox, etc.). */
function belongsInView(item, view) {
  if (view === 'archived') return item.archived;
  if (item.archived) return false;
  if (view === 'inbox') return !item.reviewed;
  if (view.startsWith('tag:')) return item.tags.includes(view.slice(4));
  const ref = stashViewRef(view);
  if (ref.kind === 'folder') return item.folderId === ref.id;
  if (ref.kind === 'list') {
    const list = smartListById(ref.id);
    if (!list) return true;
    if (list.type && item.type !== list.type) return false;
    if (list.tag && !item.tags.includes(list.tag)) return false;
    if (list.folderId && item.folderId !== list.folderId) return false;
    return true; // the words themselves are matched by the server
  }
  if (ITEM_TYPES.includes(view)) return item.type === view;
  return true;
}

/* ---- rendering */

export function showStash() {
  const view = state.route.id;
  state.stash.openId = null;
  els.stash.innerHTML = `
    <div class="stash-head">
      <div class="tag-chips" data-type-chips>${typeChips(view)}</div>
      <div class="tag-chips" data-tag-chips>${tagChips(view)}</div>
      <div class="stash-tools" data-stash-tools>${toolsHTML(view)}</div>
    </div>
    <div class="articles stash-list" data-stash-items></div>
    <div class="list-end" data-stash-end></div>`;
  reloadItems();
}

/** Keeping a search or filter: turn it into a smart list. A smart list itself can be edited. */
function toolsHTML(view) {
  if (stashViewRef(view).kind === 'list') {
    return `<button type="button" class="btn btn-sm" data-stash-action="edit-list">${icon('sliders')}Edit smart list</button>`;
  }
  const filtered = Boolean(state.stash.query) || view.startsWith('tag:') || ITEM_TYPES.includes(view)
    || stashViewRef(view).kind === 'folder';
  return filtered
    ? `<button type="button" class="btn btn-sm" data-stash-action="save-list">${icon('search')}Save as smart list</button>`
    : '';
}

export function renderStashTools() {
  const tools = $('[data-stash-tools]', els.stash);
  if (tools) tools.innerHTML = toolsHTML(state.route.id);
}

/** Runs the toolbar search again over the stash. */
export function searchStash() {
  renderStashTools();
  reloadItems();
}

export function reloadItems() {
  state.stash.items = { items: [], byId: new Map(), done: false, loading: false };
  state.stash.openId = null;
  const container = $('[data-stash-items]', els.stash);
  if (container) container.innerHTML = '';
  loadMoreItems();
}

/** Type filters, for the types that have something saved. */
function typeChips(view) {
  const counts = state.stash.summary.by_type;
  return ITEM_TYPES
    .filter((type) => counts[type] || type === view)
    .map((type) => `<button type="button" class="chip ${type === view ? 'active' : ''}" data-type-filter="${type}">${icon(TYPE_ICONS[type])}${STASH_VIEWS[type]} <span>${counts[type] || 0}</span></button>`)
    .join('');
}

function tagChips(view) {
  const active = view?.startsWith('tag:') ? view.slice(4) : null;
  return state.stash.tags
    .filter((tag) => tag.count || tag.name === active)
    .map((tag) => `<button type="button" class="chip ${tag.name === active ? 'active' : ''}" data-tag="${esc(tag.name)}">#${esc(tag.name)} <span>${tag.count}</span></button>`)
    .join('');
}

async function loadMoreItems() {
  const list = state.stash.items;
  const end = $('[data-stash-end]', els.stash);
  if (!list || !end || list.loading || list.done) return;
  list.loading = true;
  const params = viewQuery(state.route.id);
  params.set('offset', list.items.length);
  end.className = 'list-end';
  end.innerHTML = '<div class="muted">Loading…</div>';

  let items;
  try {
    items = await api('GET', `/api/items?${params}`);
  } catch (err) {
    if (list !== state.stash.items) return;
    list.loading = false;
    end.innerHTML = `<div class="muted">${esc(err.message)}</div>`;
    return;
  }
  const container = $('[data-stash-items]', els.stash);
  if (list !== state.stash.items || !container) return; // the view changed while loading

  list.loading = false;
  list.done = items.length < PAGE_SIZE;
  const fresh = items.filter((item) => !list.byId.has(item.id));
  for (const item of fresh) {
    list.items.push(item);
    list.byId.set(item.id, item);
  }
  container.insertAdjacentHTML('beforeend', fresh.map(itemHTML).join(''));
  renderEnd();
  watchPending();
}

function renderEnd() {
  const list = state.stash.items;
  const end = $('[data-stash-end]', els.stash);
  if (!end || !list) return;
  if (!list.done) {
    end.className = 'list-end';
    end.innerHTML = '<button class="btn btn-sm" data-stash-action="more">Load more</button>';
    return;
  }
  if (list.items.length) {
    end.className = 'list-end';
    end.innerHTML = '';
    return;
  }
  const view = state.route.id;
  let title = 'Nothing saved here yet';
  let sub = '';
  if (state.stash.query) {
    title = 'Nothing matches your search';
  } else if (view === 'inbox') {
    title = 'Inbox zero';
    sub = 'Save links, snippets and screenshots with + Add, the browser extension, email, or your phone.';
  } else if (view === 'archived') {
    title = 'Nothing archived yet';
  }
  end.className = 'list-end done empty';
  end.innerHTML = `${icon('circle-check')}<div class="big">${esc(title)}</div><div>${esc(sub)}</div>
    ${view === 'inbox' && !state.stash.query ? `<p><button class="btn btn-sm btn-primary" data-stash-action="capture">${icon('plus')}Save something</button></p>` : ''}`;
}

function itemHTML(item) {
  const ts = timestamp(item.createdAt);
  const host = hostOf(item.url);
  const folder = item.folderId ? stashFolderById(item.folderId) : null;
  return `
    <article class="item stash-item ${item.reviewed ? 'read' : ''}" data-id="${item.id}" draggable="true">
      <div class="item-row" data-stash-action="open">
        ${item.imagePath || item.preview?.image ? `<img class="thumb" src="${esc(item.imagePath || item.preview.image)}" alt="" loading="lazy">` : ''}
        <div class="item-main">
          <h2 class="item-title">${esc(itemTitle(item))}</h2>
          <div class="item-meta">
            <span class="type-badge">${icon(TYPE_ICONS[item.type])}${TYPE_LABELS[item.type]}</span>
            ${host ? `<span class="dot">·</span><span class="feed-name">${esc(host)}</span>` : ''}
            ${folder ? `<span class="dot">·</span><span class="folder-name">${icon('folder')}${esc(folder.name)}</span>` : ''}
            ${item.links.length > 1 ? `<span class="dot">·</span><span class="link-count">${item.links.length} links</span>` : ''}
            <span class="dot">·</span><span class="age" title="${esc(fullDate(ts))}">${ago(ts)}</span>
            <span class="dot">·</span><span class="source">via ${esc(item.source)}</span>
            ${item.tags.map((tag) => `<span class="tag">#${esc(tag)}</span>`).join('')}
          </div>
          ${item.content && item.title ? `<p class="item-summary">${esc(item.content)}</p>`
    : item.preview?.description ? `<p class="item-summary">${esc(item.preview.description)}</p>` : ''}
        </div>
        <div class="item-tools">
          <button class="icon-btn" data-stash-action="review" title="${item.reviewed ? 'Back to Inbox' : 'Mark reviewed'}">${icon(item.reviewed ? 'inbox' : 'check')}</button>
          <button class="icon-btn" data-stash-action="archive" title="${item.archived ? 'Unarchive' : 'Archive'}">${icon('archive')}</button>
        </div>
      </div>
    </article>`;
}

/** The item's links, unless it's a link item whose only link is already its title. */
function linksHTML(item) {
  if (!item.links.length || (item.type === 'link' && item.links.length === 1)) return '';
  return `<ul class="stash-links">${item.links.map((link) => {
    const href = httpUrl(link.url);
    const text = esc(link.label || link.url);
    const host = link.label ? hostOf(link.url) : '';
    return `<li>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text}${host ? `<span class="link-host">${esc(host)}</span>` : ''}</li>`;
  }).join('')}</ul>`;
}

function readerHTML(item) {
  const link = httpUrl(item.url);
  const title = esc(itemTitle(item));
  const tags = item.tags.length
    ? item.tags.map((tag) => `<button type="button" class="chip" data-tag="${esc(tag)}">#${esc(tag)}</button>`).join('')
    : '<span class="muted">No tags</span>';
  return `
    <h1 class="reader-title">${link && item.type === 'link' ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}</h1>
    <div class="reader-meta">
      <span class="type-badge">${icon(TYPE_ICONS[item.type])}${TYPE_LABELS[item.type]}</span>
      <span>·</span><span>${esc(fullDate(timestamp(item.createdAt)))}</span>
      <span>·</span><span>via ${esc(item.source)}</span>
    </div>
    <div class="reader-bar">
      <button class="btn btn-sm" data-stash-action="review">${icon(item.reviewed ? 'inbox' : 'check')}${item.reviewed ? 'Back to Inbox' : 'Mark reviewed'}</button>
      <button class="btn btn-sm" data-stash-action="archive">${icon('archive')}${item.archived ? 'Unarchive' : 'Archive'}</button>
      ${link ? `<a class="btn btn-sm" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${icon('external')}Open link</a>` : ''}
      <label class="folder-pick">${icon('folder')}
        <select data-item-folder aria-label="Folder">${folderOptionsHTML(item.folderId)}</select></label>
      <button class="btn btn-sm" data-stash-action="edit">${icon('text')}Edit</button>
      <button class="btn btn-sm" data-stash-action="delete">${icon('trash')}Delete</button>
      <button class="btn btn-sm" data-stash-action="close">${icon('x')}Close</button>
    </div>
    <div class="reader-body stash-body">
      ${item.imagePath ? `<a href="${esc(item.imagePath)}" target="_blank" rel="noopener"><img src="${esc(item.imagePath)}" alt=""></a>` : ''}
      ${item.content ? `<div class="stash-text">${esc(item.content)}</div>` : ''}
      ${linksHTML(item)}
    </div>
    <div class="stash-tags">${tags}<button type="button" class="btn btn-sm" data-stash-action="edit">${icon('tag')}Edit tags</button></div>
    <div class="saved-page" data-saved-page></div>`;
}

const itemEl = (id) => $(`.item[data-id="${id}"]`, els.stash);

function openItem(id) {
  if (state.stash.openId === id) {
    closeStashItem();
    return;
  }
  closeStashItem();
  const item = state.stash.items?.byId.get(id);
  const el = itemEl(id);
  if (!item || !el) return;
  state.stash.openId = id;
  el.classList.add('open');
  el.insertAdjacentHTML('beforeend', `<div class="reader">${readerHTML(item)}</div>`);
  const box = els.content.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  if (r.top < box.top) els.content.scrollTop += r.top - box.top;
  loadSavedPage(item);
}

/** Shows what FeedStash saved of the item's web page: the readable copy, or why there isn't one (yet). */
async function loadSavedPage(item) {
  const box = $(`.item[data-id="${item.id}"] [data-saved-page]`, els.stash);
  const page = item.preview;
  if (!box || !page) return;
  const again = (label) => `<button type="button" class="btn btn-sm" data-stash-action="refetch">${icon('refresh')}${label}</button>`;
  if (isSaving(item)) {
    box.innerHTML = page.error
      ? `<p class="muted">Couldn't save a copy of this page yet (${esc(page.error)}); trying again soon. ${again('Try now')}</p>`
      : '<p class="muted">Saving a copy of this page…</p>';
    return;
  }
  if (!page.hasCopy) {
    // A site that turns the server away will do it again; the browser extension sends the page it can see.
    const blocked = /blocked/i.test(page.error || '')
      ? ' Saving this page from the FeedStash browser extension keeps a copy of what you see.' : '';
    if (page.status === 'failed') box.innerHTML = `<p class="muted">Couldn't save a copy of this page: ${esc(page.error || 'unknown error')}.${esc(blocked)} ${again('Try again')}</p>`;
    else if (page.status === 'skipped') box.innerHTML = `<p class="muted">No copy saved: ${esc(page.error || 'not a web page')}.</p>`;
    else box.innerHTML = '';
    return;
  }
  box.innerHTML = '<p class="muted">Loading the saved copy…</p>';
  try {
    const copy = await api('GET', `/api/items/${item.id}/page`);
    if (state.stash.openId !== item.id || !box.isConnected) return;
    box.innerHTML = `
      <div class="saved-page-head"><span>Saved copy</span>
        ${copy.fetchedAt ? `<span class="muted">${esc(fullDate(timestamp(copy.fetchedAt)))}</span>` : ''}
        ${again('Save again')}</div>
      <div class="reader-body saved-page-body"></div>`;
    $('.saved-page-body', box).replaceChildren(sanitize(copy.html || ''));
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

async function refetchPage(item) {
  try {
    await api('POST', `/api/items/${item.id}/page/refresh`);
    applyUpdate({ ...item, preview: { ...item.preview, status: 'pending', hasCopy: false, error: null } });
    toast('Saving the page again…');
  } catch (err) {
    toast(err.message, { error: true });
  }
}

/* While pages are being saved, check back on the items shown so their previews appear without a reload.
   Items waiting to retry after an error aren't polled. */
let pendingTimer = null;
function watchPending() {
  clearTimeout(pendingTimer);
  if (state.route.scope !== 'stash') return;
  const waiting = (state.stash.items?.items || [])
    .filter((item) => isSaving(item) && !item.preview.error)
    .slice(0, 10);
  if (!waiting.length) return;
  pendingTimer = setTimeout(async () => {
    for (const item of waiting) {
      try {
        const fresh = await api('GET', `/api/items/${item.id}`);
        if (fresh.preview?.status !== item.preview?.status || fresh.title !== item.title) applyUpdate(fresh);
      } catch {
        /* deleted meanwhile */
      }
    }
    watchPending();
  }, 3000);
}

export function closeStashItem() {
  const id = state.stash.openId;
  if (id == null) return;
  state.stash.openId = null;
  const el = itemEl(id);
  if (!el) return;
  el.classList.remove('open');
  $('.reader', el)?.remove();
}

/** Puts a changed item back into the list, or takes it out if it no longer belongs in this view. */
function applyUpdate(updated) {
  const list = state.stash.items;
  if (!list || state.route.scope !== 'stash') return;
  const el = itemEl(updated.id);
  if (!belongsInView(updated, state.route.id)) {
    list.byId.delete(updated.id);
    list.items = list.items.filter((item) => item.id !== updated.id);
    if (state.stash.openId === updated.id) state.stash.openId = null;
    el?.remove();
    renderEnd();
    return;
  }
  list.byId.set(updated.id, updated);
  list.items = list.items.map((item) => (item.id === updated.id ? updated : item));
  if (!el) return;
  const wasOpen = state.stash.openId === updated.id;
  el.outerHTML = itemHTML(updated);
  if (wasOpen) {
    state.stash.openId = null;
    openItem(updated.id);
  }
  watchPending();
}

/** Anything saved since this list was drawn — by email, a client, or another device — brought in without a reload. */
export async function pollStashForNew() {
  const list = state.stash.items;
  if (state.route.scope !== 'stash' || !list || list.loading) return;
  let fresh;
  try {
    fresh = await api('GET', `/api/items?${viewQuery(state.route.id)}`);
  } catch {
    return; // offline or restarting; the next tick tries again
  }
  if (list !== state.stash.items) return; // the view changed while loading
  const added = fresh.filter((item) => !list.byId.has(item.id));
  if (!added.length) return;
  // Don't shuffle the list under someone who's reading; offer a button instead.
  if (els.content.scrollTop < 40 && state.stash.openId == null) reloadItems();
  else showNewBanner(added.length, 'new item');
}

/** Reloads stash counts and tags for the sidebar, header and tag chips. */
export async function refreshStashCounts() {
  const [summary, tags] = await Promise.all([api('GET', '/api/stash/summary'), api('GET', '/api/tags')]);
  state.stash.summary = summary;
  state.stash.tags = tags;
  renderNav();
  renderHeader();
  if (state.route.scope !== 'stash') return;
  renderStashTools();
  const types = $('[data-type-chips]', els.stash);
  if (types) types.innerHTML = typeChips(state.route.id);
  const chips = $('[data-tag-chips]', els.stash);
  if (chips) chips.innerHTML = tagChips(state.route.id);
}

/* ---- actions */

async function changeItem(item, fields, { message, undo }) {
  try {
    applyUpdate(await api('PATCH', `/api/items/${item.id}`, fields));
    await refreshStashCounts();
    toast(message, {
      action: 'Undo',
      onAction: async () => {
        const restored = await api('PATCH', `/api/items/${item.id}`, undo);
        await refreshStashCounts();
        if (state.route.scope !== 'stash') return;
        if (state.stash.items?.byId.has(restored.id)) applyUpdate(restored);
        else if (belongsInView(restored, state.route.id)) reloadItems();
      },
    });
  } catch (err) {
    toast(err.message, { error: true });
  }
}

const toggleReviewed = (item) => changeItem(item, { reviewed: !item.reviewed }, {
  message: item.reviewed ? 'Moved back to the Inbox' : 'Marked reviewed',
  undo: { reviewed: item.reviewed },
});

const toggleArchived = (item) => changeItem(item, { archived: !item.archived }, {
  message: item.archived ? 'Unarchived' : 'Archived',
  undo: { archived: item.archived },
});

/** Files an item in a stash folder, or takes it out of one (folderId null). */
export function moveItemToFolder(itemId, folderId) {
  const item = state.stash.items?.byId.get(itemId);
  if (!item || (item.folderId ?? null) === (folderId ?? null)) return;
  const name = folderId ? stashFolderById(folderId)?.name : null;
  return changeItem(item, { folderId: folderId ?? null }, {
    message: name ? `Filed in ${name}` : 'Taken out of its folder',
    undo: { folderId: item.folderId ?? null },
  });
}

async function editItem(item) {
  let dialogEl = null;
  const updated = await modal({
    title: 'Edit',
    confirmText: 'Save',
    html: `
      <label>Title<input type="text" name="title" value="${esc(item.title || '')}" maxlength="1000" autocomplete="off"></label>
      <label>Notes<textarea name="content" rows="4">${esc(item.content || '')}</textarea></label>
      <div class="field-group"><span class="field-label">Links <small>(the first is the primary link)</small></span>${linkRowsHTML(item.links)}</div>
      <label><span>Tags <small>(separate with commas)</small></span><input type="text" name="tags" value="${esc(item.tags.join(', '))}" placeholder="reading, later" autocomplete="off"></label>
      <label>Folder<select name="folder">${folderOptionsHTML(item.folderId)}</select></label>`,
    onOpen: (dialog) => {
      dialogEl = dialog;
      wireLinkRows(dialog);
    },
    onSubmit: (fd) => api('PATCH', `/api/items/${item.id}`, {
      title: (fd.get('title') || '').trim() || null,
      content: fd.get('content') || null,
      links: collectLinks(dialogEl),
      tags: fd.get('tags') || '',
      folderId: fd.get('folder') ? Number(fd.get('folder')) : null,
    }),
  });
  if (!updated || updated === true) return;
  applyUpdate(updated);
  refreshStashCounts();
}

async function deleteItem(item) {
  const ok = await modal({
    title: 'Delete this item?',
    confirmText: 'Delete',
    danger: true,
    html: `<p>“${esc(itemTitle(item))}” will be removed for good${item.imagePath ? ', along with its image' : ''}.</p>`,
    onSubmit: () => api('DELETE', `/api/items/${item.id}`),
  });
  if (!ok) return;
  applyUpdate({ ...item, archived: true, id: item.id, _deleted: true });
  const list = state.stash.items;
  if (list?.byId.has(item.id)) { // still shown (e.g. in Archive): remove it explicitly
    list.byId.delete(item.id);
    list.items = list.items.filter((i) => i.id !== item.id);
    itemEl(item.id)?.remove();
    renderEnd();
  }
  await refreshStashCounts();
  toast('Deleted');
}

export async function captureDialog({ type = 'link' } = {}) {
  let pastedImage = null;
  let dialogEl = null;
  const item = await modal({
    title: 'Save to your stash',
    confirmText: 'Save',
    busyText: 'Saving…',
    html: `
      <div class="type-switch" role="radiogroup" aria-label="What are you saving?">
        ${['link', 'snippet', 'screenshot'].map((t) => `
          <label class="type-option"><input type="radio" name="type" value="${t}" ${t === type ? 'checked' : ''}>${icon(TYPE_ICONS[t])}${TYPE_LABELS[t]}</label>`).join('')}
      </div>
      <label data-for="snippet">Notes<textarea name="content" rows="6" placeholder="Paste text, or write up what these links are about"></textarea></label>
      <div data-for="link snippet" class="field-group"><span class="field-label" data-links-label>Links</span>${linkRowsHTML()}</div>
      <div data-for="screenshot" class="capture-image">
        <label>Image<input type="file" name="image" accept="image/*"></label>
        <p class="muted">Or paste an image (Ctrl+V) while this dialog is open.</p>
        <img class="capture-preview" alt="" hidden>
      </div>
      <label>Title (optional)<input type="text" name="title" maxlength="1000" autocomplete="off"></label>
      <label>Tags (optional)<input type="text" name="tags" placeholder="reading, later" autocomplete="off"></label>
      <label>Folder<select name="folder">${folderOptionsHTML(stashViewRef(state.route.id).kind === 'folder' ? stashViewRef(state.route.id).id : null)}</select></label>`,
    onOpen: (dialog) => {
      dialogEl = dialog;
      wireLinkRows(dialog);
      const preview = $('.capture-preview', dialog);
      const showPreview = (file) => {
        preview.src = URL.createObjectURL(file);
        preview.hidden = false;
      };
      const syncFields = () => {
        const current = $('input[name=type]:checked', dialog).value;
        $$('[data-for]', dialog).forEach((el) => { el.hidden = !el.dataset.for.split(' ').includes(current); });
        $('[data-links-label]', dialog).textContent = current === 'snippet' ? 'Links (optional)' : 'Links';
      };
      $$('input[name=type]', dialog).forEach((radio) => radio.addEventListener('change', () => {
        syncFields();
        $('[data-for]:not([hidden]) input, [data-for]:not([hidden]) textarea', dialog)?.focus();
      }));
      $('input[name=image]', dialog).addEventListener('change', (e) => {
        pastedImage = null;
        if (e.target.files[0]) showPreview(e.target.files[0]);
      });
      dialog.addEventListener('paste', (e) => {
        const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith('image/'));
        if (!file) return; // plain text pastes normally into the focused field
        e.preventDefault();
        pastedImage = file;
        $('input[name=type][value=screenshot]', dialog).checked = true;
        syncFields();
        showPreview(file);
      });
      syncFields();
    },
    onSubmit: async (fd) => {
      const kind = fd.get('type');
      const body = new FormData();
      body.set('type', kind);
      body.set('source', 'web');
      for (const key of ['title', 'tags']) {
        const value = (fd.get(key) || '').trim();
        if (value) body.set(key, value);
      }
      if (fd.get('folder')) body.set('folderId', fd.get('folder'));
      const links = collectLinks(dialogEl);
      if (kind === 'link') {
        if (!links.length) throw new Error('Enter a URL');
        body.set('links', JSON.stringify(links));
      } else if (kind === 'snippet') {
        const content = fd.get('content') || '';
        if (!content.trim() && !links.length) throw new Error('Enter some text or a link');
        if (content.trim()) body.set('content', content);
        if (links.length) body.set('links', JSON.stringify(links));
      } else {
        const file = pastedImage || fd.get('image');
        if (!file || !file.size) throw new Error('Choose or paste an image');
        body.set('image', file, file.name || 'pasted.png');
      }
      return api('POST', '/api/items', body);
    },
  });
  if (!item || item === true) return;
  await refreshStashCounts();
  if (state.route.scope === 'stash') {
    if (belongsInView(item, state.route.id)) reloadItems();
    toast('Saved to your stash');
  } else {
    toast('Saved to your stash', { action: 'View', onAction: () => navigate('#/stash/inbox') });
  }
}

export async function stashArticle(article) {
  try {
    const res = await api('POST', `/api/articles/${article.id}/stash`);
    await refreshStashCounts();
    toast(res.created ? 'Saved to your stash' : 'Already in your stash', {
      action: 'View',
      onAction: () => navigate(res.item.reviewed ? '#/stash/all' : '#/stash/inbox'),
    });
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireStash() {
  els.stash.addEventListener('click', (e) => {
    const typeChip = e.target.closest('[data-type-filter]');
    if (typeChip) {
      const type = typeChip.dataset.typeFilter;
      navigate(state.route.id === type ? '#/stash/all' : `#/stash/${type}`);
      return;
    }
    const chip = e.target.closest('[data-tag]');
    if (chip) {
      const tag = chip.dataset.tag;
      navigate(state.route.id === `tag:${tag}` ? '#/stash/all' : `#/stash/tag/${encodeURIComponent(tag)}`);
      return;
    }
    const action = e.target.closest('[data-stash-action]')?.dataset.stashAction;
    if (!action) return;
    if (action === 'more') return loadMoreItems();
    if (action === 'capture') return captureDialog();
    if (action === 'save-list') return saveCurrentAsSmartList();
    if (action === 'edit-list') return editSmartList(stashViewRef(state.route.id).id);
    const item = state.stash.items?.byId.get(Number(e.target.closest('.item')?.dataset.id));
    if (!item) return;
    switch (action) {
      case 'open': openItem(item.id); break;
      case 'close': closeStashItem(); break;
      case 'review': toggleReviewed(item); break;
      case 'archive': toggleArchived(item); break;
      case 'edit': editItem(item); break;
      case 'delete': deleteItem(item); break;
      case 'refetch': refetchPage(item); break;
    }
  });

  els.stash.addEventListener('change', (e) => {
    if (!e.target.matches('[data-item-folder]')) return;
    const id = Number(e.target.closest('.item')?.dataset.id);
    moveItemToFolder(id, e.target.value ? Number(e.target.value) : null);
  });

  // Items can be dragged onto a folder in the sidebar.
  els.stash.addEventListener('dragstart', (e) => {
    const el = e.target.closest('.stash-item');
    if (!el) return;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData(ITEM_DRAG, el.dataset.id);
    e.dataTransfer.setData('text/plain', ''); // Firefox won't start a drag without this
  });

  els.content.addEventListener('scroll', () => {
    if (state.route.scope !== 'stash') return;
    const c = els.content;
    if (c.scrollTop + c.clientHeight > c.scrollHeight - 800) loadMoreItems();
  }, { passive: true });
}
