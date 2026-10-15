/* The stash: links, notes, screenshots and emails saved from anywhere. New items wait in the Inbox.
   (Notes are type "snippet" in the API, which clients depend on.) */

import { api } from './api.js';
import { showNewBanner } from './autorefresh.js';
import { modal, promptDialog, toast } from './dialogs.js';
import { icon } from './icons.js';
import { collectLinks, linkRowsHTML, wireLinkRows } from './links.js';
import { openMenu } from './menus.js';
import { navigate } from './router.js';
import { sanitize } from './sanitize.js';
import { renderHeader, renderNav } from './sidebar.js';
import { editSmartList, fileItemInNewFolder, saveCurrentAsSmartList } from './stashlists.js';
import { els, ITEM_TYPES, smartListById, stashFolderById, STASH_VIEWS, state, stashViewRef } from './state.js';
import { attachTagPicker } from './tagpicker.js';
import { $, $$, ago, esc, fullDate, loadJSON, saveJSON } from './util.js';

const PAGE_SIZE = 50;
/** Drag type for moving a saved item onto a folder in the sidebar. */
export const ITEM_DRAG = 'application/x-feedstash-item';
export const TYPE_LABELS = { link: 'Link', snippet: 'Note', screenshot: 'Screenshot', email: 'Email' };
const TYPE_ICONS = { link: 'external', snippet: 'text', screenshot: 'image', email: 'mail' };

/* ---- list, grid or tiles: chosen per view (folder, smart list, tag, kind…), kept in this browser */

const LAYOUTS = { list: 'List', grid: 'Grid', tiles: 'Tiles' };
const LAYOUT_KEY = 'reader.stashLayouts';
let layouts = loadJSON(LAYOUT_KEY, {});
const layoutFor = (view) => (Object.hasOwn(LAYOUTS, layouts[view]) ? layouts[view] : 'list');

function layoutSwitchHTML(view) {
  const current = layoutFor(view);
  return `<div class="layout-switch" role="group" aria-label="Layout">${Object.entries(LAYOUTS).map(([key, label]) => `
    <button type="button" class="icon-btn ${key === current ? 'on' : ''}" data-stash-layout-choice="${key}"
      title="${label}" aria-pressed="${key === current}">${icon(`view-${key}`)}</button>`).join('')}</div>`;
}

function setLayout(view, layout) {
  if (layout === 'list') delete layouts[view];
  else layouts[view] = layout;
  saveJSON(LAYOUT_KEY, layouts);
  closeStashItem();
  applyStashLayout();
  renderStashTools();
}

/* Grid cards keep their own height (a masonry layout): each spans as many of the grid's short rows as it needs,
   measured again whenever it changes size (an image loads, the card opens, the window narrows). */
const GRID_ROW = 4;
const GRID_GAP = 14;
const cardSizer = new ResizeObserver((entries) => entries.forEach((entry) => spanCard(entry.target)));

function spanCard(card) {
  if (layoutFor(state.route.id) !== 'grid' || !card.isConnected) {
    card.style.gridRowEnd = '';
    return;
  }
  const height = card.getBoundingClientRect().height;
  card.style.gridRowEnd = `span ${Math.max(1, Math.ceil((height + GRID_GAP) / GRID_ROW))}`;
}

function watchCards() {
  const container = $('[data-stash-items]', els.stash);
  if (container) $$('.stash-item', container).forEach((card) => cardSizer.observe(card));
}

/** Stops measuring a card that is about to be replaced or removed. */
function forgetCard(card) {
  if (card) cardSizer.unobserve(card);
}

function applyStashLayout() {
  const layout = layoutFor(state.route.id);
  els.stash.dataset.stashLayout = layout;
  const container = $('[data-stash-items]', els.stash);
  if (!container) return;
  container.classList.toggle('cards', layout !== 'list');
  container.classList.toggle('cards-grid', layout === 'grid');
  container.classList.toggle('cards-tiles', layout === 'tiles');
  $$('.stash-item', container).forEach(spanCard);
}

const timestamp = (iso) => Math.floor(Date.parse(iso) / 1000);
const httpUrl = (url) => (/^https?:\/\//i.test(url || '') ? url : null);
const firstLine = (text) => (text || '').trim().split('\n')[0].slice(0, 200);
const itemTitle = (item) => item.title || (item.type === 'link' ? '' : firstLine(item.content))
  || item.links[0]?.label || item.preview?.title || item.url || '(untitled)';
/** Every picture, for servers older than several pictures per item too. */
const picturesOf = (item) => item.images || (item.imagePath ? [item.imagePath] : []);
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
export function folderOptionsHTML(selected, { allowNew = false } = {}) {
  const options = (state.stash.summary.folders || [])
    .map((f) => `<option value="${f.id}" ${f.id === selected ? 'selected' : ''}>${esc(f.name)}</option>`)
    .join('');
  return `<option value="" ${selected ? '' : 'selected'}>No folder</option>${options}`
    + (allowNew ? '<option value="__new">+ New folder…</option>' : '');
}

/** A folder picker that can also make one, so you don't have to leave what you're writing. */
function folderFieldHTML(selected) {
  return `
    <label>Folder<select name="folder">${folderOptionsHTML(selected, { allowNew: true })}</select></label>
    <label data-new-stash-folder hidden>New folder name
      <input type="text" name="folder_name" maxlength="200" autocomplete="off"></label>`;
}

function wireFolderField(dialog) {
  const select = $('select[name=folder]', dialog);
  const field = $('[data-new-stash-folder]', dialog);
  select?.addEventListener('change', () => {
    field.hidden = select.value !== '__new';
    if (!field.hidden) $('input', field).focus();
  });
}

/** The folder the dialog ended on, making it first if "+ New folder…" was chosen. */
async function chosenFolderId(fd) {
  const value = fd.get('folder');
  if (value !== '__new') return value ? Number(value) : null;
  const name = (fd.get('folder_name') || '').trim();
  if (!name) throw new Error('Enter a name for the new folder');
  const existing = (state.stash.summary.folders || []).find((f) => f.name.toLowerCase() === name.toLowerCase());
  return existing ? existing.id : (await api('POST', '/api/stash/folders', { name })).id;
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
  applyStashLayout();
  reloadItems();
}

/** Keeping a search or filter: turn it into a smart list. A smart list itself can be edited. */
function toolsHTML(view) {
  return `<div class="stash-tool-buttons">${toolButtonsHTML(view)}</div>${layoutSwitchHTML(view)}`;
}

function toolButtonsHTML(view) {
  if (stashViewRef(view).kind === 'list') {
    return `<button type="button" class="btn btn-sm" data-stash-action="edit-list">${icon('sliders')}Edit smart list</button>`;
  }
  const filtered = Boolean(state.stash.query) || view.startsWith('tag:') || ITEM_TYPES.includes(view)
    || stashViewRef(view).kind === 'folder';
  const rename = view.startsWith('tag:')
    ? `<button type="button" class="btn btn-sm" data-stash-action="rename-tag">${icon('tag')}Rename or merge #${esc(view.slice(4))}</button>`
    : '';
  return (filtered
    ? `<button type="button" class="btn btn-sm" data-stash-action="save-list">${icon('search')}Save as smart list</button>`
    : '') + rename;
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
  cardSizer.disconnect();
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
  const chips = state.stash.tags
    .filter((tag) => tag.count || tag.name === active)
    .map((tag) => `<button type="button" class="chip ${tag.name === active ? 'active' : ''}" data-tag="${esc(tag.name)}">#${esc(tag.name)} <span>${tag.count}</span></button>`)
    .join('');
  return chips ? `${chips}<button type="button" class="chip chip-manage" data-stash-action="manage-tags">${icon('tag')}Manage tags</button>` : '';
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
  watchCards();
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
    sub = 'Save links, notes and screenshots with + Add, the browser extension, email, or your phone.';
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
            ${picturesOf(item).length > 1 ? `<span class="dot">·</span><span class="picture-count">${icon('image')}${picturesOf(item).length}</span>` : ''}
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
          <button class="icon-btn" data-stash-action="menu" title="More">${icon('more')}</button>
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
      ${picturesOf(item).map((path) => `<a href="${esc(path)}" target="_blank" rel="noopener"><img src="${esc(path)}" alt=""></a>`).join('')}
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
    forgetCard(el);
    el?.remove();
    renderEnd();
    return;
  }
  list.byId.set(updated.id, updated);
  list.items = list.items.map((item) => (item.id === updated.id ? updated : item));
  if (!el) return;
  const wasOpen = state.stash.openId === updated.id;
  forgetCard(el);
  el.outerHTML = itemHTML(updated);
  watchCards();
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

/** The tag picker under a dialog's tags field, with the page's tags at once and the server's current list after. */
function attachFreshTagPicker(input) {
  const update = attachTagPicker(input, state.stash.tags);
  api('GET', '/api/tags').then((tags) => {
    state.stash.tags = tags;
    if (input.isConnected) update(tags);
  }).catch(() => {}); // the page's own list is still there to suggest from
}

/** Renames a tag on every item; naming an existing tag merges the two (e.g. #vibes into #vibe). */
/** "Manage tags" goes to Settings → Tags, where tags are checked off and merged or renamed. */
async function manageTags() {
  navigate('#/settings');
  for (let i = 0; i < 20; i += 1) {
    const heading = document.querySelector('[data-tags-heading]');
    if (heading) {
      heading.scrollIntoView({ block: 'start' });
      return;
    }
    await new Promise((resolve) => { setTimeout(resolve, 50); });
  }
}

async function renameTag(name, { go = true } = {}) {
  let result = null;
  const value = await promptDialog({
    title: `Rename or merge #${name}`,
    label: 'New name (an existing tag merges them)',
    value: name,
    confirmText: 'Rename',
    onSubmit: async (newName) => {
      result = await api('POST', '/api/tags/rename', { name, newName });
    },
  });
  if (!value || !result) return;
  await refreshStashCounts();
  if (go) navigate(`#/stash/tag/${encodeURIComponent(result.name)}`);
  const items = `${result.items} item${result.items === 1 ? '' : 's'}`;
  toast(result.merged ? `Merged #${name} into #${result.name} (${items})` : `Renamed #${name} to #${result.name} (${items})`);
}

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

/** Everything you can do to a saved item without opening it. */
function itemMenuItems(item) {
  const items = [
    [item.reviewed ? 'Back to Inbox' : 'Mark reviewed', () => toggleReviewed(item)],
    ['Edit…', () => editItem(item)],
  ];
  for (const folder of state.stash.summary.folders || []) {
    if (folder.id !== item.folderId) items.push([`Move to ${folder.name}`, () => moveItemToFolder(item.id, folder.id)]);
  }
  if (item.folderId) items.push(['Take out of its folder', () => moveItemToFolder(item.id, null)]);
  items.push(['Move to a new folder…', () => fileItemInNewFolder(item.id)]);
  items.push([item.archived ? 'Unarchive' : 'Archive', () => toggleArchived(item)]);
  items.push(['Delete', () => deleteItem(item), 'danger']);
  return items;
}

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

/* ---- pictures in the Save and Edit dialogs: thumbnails with a remove button; more from a file picker or a paste */

function picturePickerHTML() {
  return `
    <div class="field-group picture-picker">
      <span class="field-label">Pictures</span>
      <div class="picture-strip" data-picture-strip></div>
      <div class="picture-actions">
        <label class="btn btn-sm">${icon('plus')}Add pictures<input type="file" accept="image/*" multiple hidden data-picture-input></label>
        <span class="muted">or paste one (Ctrl+V)</span>
      </div>
    </div>`;
}

/** Wires the picker in `dialog`. `existing` are the item's pictures (paths on the server). */
function wirePicturePicker(dialog, existing = []) {
  const kept = [...existing];
  const added = []; // { file, url }
  const strip = $('[data-picture-strip]', dialog);
  const thumb = (src, attr) => `<figure class="picture-thumb"><img src="${esc(src)}" alt="">
    <button type="button" class="icon-btn" ${attr} title="Remove">${icon('x')}</button></figure>`;
  const render = () => {
    strip.innerHTML = [
      ...kept.map((path, i) => thumb(path, `data-remove-kept="${i}"`)),
      ...added.map((picture, i) => thumb(picture.url, `data-remove-added="${i}"`)),
    ].join('');
    strip.hidden = !kept.length && !added.length;
  };
  const addFiles = (files) => {
    for (const file of files) {
      if (file.type.startsWith('image/')) added.push({ file, url: URL.createObjectURL(file) });
    }
    render();
  };
  strip.addEventListener('click', (e) => {
    const button = e.target.closest('button');
    if (!button) return;
    if (button.dataset.removeKept != null) kept.splice(Number(button.dataset.removeKept), 1);
    else added.splice(Number(button.dataset.removeAdded), 1);
    render();
  });
  $('[data-picture-input]', dialog).addEventListener('change', (e) => {
    addFiles([...e.target.files]);
    e.target.value = '';
  });
  dialog.addEventListener('close', () => added.forEach((picture) => URL.revokeObjectURL(picture.url)));
  render();
  return { kept: () => [...kept], files: () => added.map((picture) => picture.file), addFiles };
}

const pastedPictures = (e) => [...(e.clipboardData?.files || [])].filter((file) => file.type.startsWith('image/'));

/** Adds pictures one request at a time (a request's size is capped). Returns the updated item, or null. */
async function uploadPictures(itemId, files) {
  let item = null;
  for (const file of files) {
    const body = new FormData();
    body.append('image', file, file.name || 'pasted.png');
    item = await api('POST', `/api/items/${itemId}/images`, body);
  }
  return item;
}

/** Uploads the rest after the item is saved; a failure is reported without losing what was saved. */
async function uploadRest(item, files) {
  if (!files.length) return item;
  try {
    return (await uploadPictures(item.id, files)) || item;
  } catch (err) {
    toast(`Saved, but not every picture was added: ${err.message}`, { error: true });
    return (await api('GET', `/api/items/${item.id}`).catch(() => null)) || item;
  }
}

async function editItem(item) {
  let dialogEl = null;
  let pictures = null;
  const updated = await modal({
    title: 'Edit',
    confirmText: 'Save',
    html: `
      <label>Title<input type="text" name="title" value="${esc(item.title || '')}" maxlength="1000" autocomplete="off"></label>
      <label>Notes<textarea name="content" rows="4">${esc(item.content || '')}</textarea></label>
      <div class="field-group"><span class="field-label">Links <small>(the first is the primary link)</small></span>${linkRowsHTML(item.links)}</div>
      <label><span>Tags <small>(separate with commas)</small></span><input type="text" name="tags" value="${esc(item.tags.join(', '))}" placeholder="reading, later" autocomplete="off"></label>
      ${picturePickerHTML()}
      ${folderFieldHTML(item.folderId)}`,
    onOpen: (dialog) => {
      dialogEl = dialog;
      wireLinkRows(dialog);
      wireFolderField(dialog);
      pictures = wirePicturePicker(dialog, picturesOf(item));
      dialog.addEventListener('paste', (e) => {
        const files = pastedPictures(e);
        if (!files.length) return;
        e.preventDefault();
        pictures.addFiles(files);
      });
      attachFreshTagPicker($('input[name=tags]', dialog));
    },
    onSubmit: async (fd) => {
      const fields = {
        title: (fd.get('title') || '').trim() || null,
        content: fd.get('content') || null,
        links: collectLinks(dialogEl),
        tags: fd.get('tags') || '',
        folderId: await chosenFolderId(fd),
      };
      const before = picturesOf(item);
      const kept = pictures.kept();
      if (kept.length !== before.length || kept.some((path, i) => path !== before[i])) fields.images = kept;
      const saved = await api('PATCH', `/api/items/${item.id}`, fields);
      return uploadRest(saved, pictures.files());
    },
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
    html: `<p>“${esc(itemTitle(item))}” will be removed for good${picturesOf(item).length ? `, along with its ${picturesOf(item).length > 1 ? 'pictures' : 'picture'}` : ''}.</p>`,
    onSubmit: () => api('DELETE', `/api/items/${item.id}`),
  });
  if (!ok) return;
  applyUpdate({ ...item, archived: true, id: item.id, _deleted: true });
  const list = state.stash.items;
  if (list?.byId.has(item.id)) { // still shown (e.g. in Archive): remove it explicitly
    list.byId.delete(item.id);
    list.items = list.items.filter((i) => i.id !== item.id);
    forgetCard(itemEl(item.id));
    itemEl(item.id)?.remove();
    renderEnd();
  }
  await refreshStashCounts();
  toast('Deleted');
}

export async function captureDialog({ type = 'link' } = {}) {
  let dialogEl = null;
  let pictures = null;
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
      <div data-for="screenshot">${picturePickerHTML()}</div>
      <label>Title (optional)<input type="text" name="title" maxlength="1000" autocomplete="off"></label>
      <label><span>Tags (optional) <small>(separate with commas)</small></span><input type="text" name="tags" placeholder="reading, later" autocomplete="off"></label>
      ${folderFieldHTML(stashViewRef(state.route.id).kind === 'folder' ? stashViewRef(state.route.id).id : null)}`,
    onOpen: (dialog) => {
      dialogEl = dialog;
      wireLinkRows(dialog);
      wireFolderField(dialog);
      pictures = wirePicturePicker(dialog);
      const syncFields = () => {
        const current = $('input[name=type]:checked', dialog).value;
        $$('[data-for]', dialog).forEach((el) => { el.hidden = !el.dataset.for.split(' ').includes(current); });
        $('[data-links-label]', dialog).textContent = current === 'snippet' ? 'Links (optional)' : 'Links';
      };
      $$('input[name=type]', dialog).forEach((radio) => radio.addEventListener('change', () => {
        syncFields();
        $('[data-for]:not([hidden]) input, [data-for]:not([hidden]) textarea', dialog)?.focus();
      }));
      dialog.addEventListener('paste', (e) => {
        const files = pastedPictures(e);
        if (!files.length) return; // plain text pastes normally into the focused field
        e.preventDefault();
        $('input[name=type][value=screenshot]', dialog).checked = true;
        syncFields();
        pictures.addFiles(files);
      });
      syncFields();
      attachFreshTagPicker($('input[name=tags]', dialog));
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
      const folderId = await chosenFolderId(fd);
      if (folderId) body.set('folderId', folderId);
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
        const [first, ...rest] = pictures.files();
        if (!first) throw new Error('Choose or paste a picture');
        body.set('image', first, first.name || 'pasted.png');
        return uploadRest(await api('POST', '/api/items', body), rest);
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
    const layoutChoice = e.target.closest('[data-stash-layout-choice]');
    if (layoutChoice) {
      setLayout(state.route.id, layoutChoice.dataset.stashLayoutChoice);
      return;
    }
    const control = e.target.closest('[data-stash-action]');
    const action = control?.dataset.stashAction;
    if (!action) return;
    if (action === 'more') return loadMoreItems();
    if (action === 'capture') return captureDialog();
    if (action === 'save-list') return saveCurrentAsSmartList();
    if (action === 'rename-tag') return renameTag(state.route.id.slice(4));
    if (action === 'manage-tags') return manageTags();
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
      case 'menu': openMenu(itemMenuItems(item), control); break;
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
