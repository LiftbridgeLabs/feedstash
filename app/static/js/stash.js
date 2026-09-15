/* The stash: links, snippets, screenshots and emails saved from anywhere. New items wait in the Inbox. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { collectLinks, linkRowsHTML, wireLinkRows } from './links.js';
import { navigate } from './router.js';
import { renderHeader, renderNav } from './sidebar.js';
import { els, ITEM_TYPES, STASH_VIEWS, state } from './state.js';
import { $, $$, ago, esc, fullDate } from './util.js';

const PAGE_SIZE = 50;
const TYPE_LABELS = { link: 'Link', snippet: 'Snippet', screenshot: 'Screenshot', email: 'Email' };
const TYPE_ICONS = { link: 'external', snippet: 'text', screenshot: 'image', email: 'mail' };

const timestamp = (iso) => Math.floor(Date.parse(iso) / 1000);
const httpUrl = (url) => (/^https?:\/\//i.test(url || '') ? url : null);
const firstLine = (text) => (text || '').trim().split('\n')[0].slice(0, 200);
const itemTitle = (item) => item.title || (item.type === 'link' ? '' : firstLine(item.content))
  || item.links[0]?.label || item.url || '(untitled)';

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
  if (view === 'inbox') params.set('reviewed', 'false');
  else if (view === 'archived') params.set('archived', 'true');
  else if (view.startsWith('tag:')) params.set('tag', view.slice(4));
  else if (ITEM_TYPES.includes(view)) params.set('type', view);
  if (state.stash.query) params.set('q', state.stash.query);
  return params;
}

/** Whether an item still belongs in the view after a change (reviewing removes it from the Inbox, etc.). */
function belongsInView(item, view) {
  if (view === 'archived') return item.archived;
  if (item.archived) return false;
  if (view === 'inbox') return !item.reviewed;
  if (view.startsWith('tag:')) return item.tags.includes(view.slice(4));
  if (ITEM_TYPES.includes(view)) return item.type === view;
  return true;
}

/* ---- rendering */

export function showStash() {
  const view = state.route.id;
  state.stash.openId = null;
  els.stash.innerHTML = `
    <div class="stash-head">
      <input type="search" class="stash-search" placeholder="Search your stash…" value="${esc(state.stash.query)}"
             data-stash-search aria-label="Search your stash">
      <div class="tag-chips" data-type-chips>${typeChips(view)}</div>
      <div class="tag-chips" data-tag-chips>${tagChips(view)}</div>
    </div>
    <div class="articles stash-list" data-stash-items></div>
    <div class="list-end" data-stash-end></div>`;
  reloadItems();
}

function reloadItems() {
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
  return `
    <article class="item stash-item ${item.reviewed ? 'read' : ''}" data-id="${item.id}">
      <div class="item-row" data-stash-action="open">
        ${item.imagePath ? `<img class="thumb" src="${esc(item.imagePath)}" alt="" loading="lazy">` : ''}
        <div class="item-main">
          <h2 class="item-title">${esc(itemTitle(item))}</h2>
          <div class="item-meta">
            <span class="type-badge">${icon(TYPE_ICONS[item.type])}${TYPE_LABELS[item.type]}</span>
            ${host ? `<span class="dot">·</span><span class="feed-name">${esc(host)}</span>` : ''}
            ${item.links.length > 1 ? `<span class="dot">·</span><span class="link-count">${item.links.length} links</span>` : ''}
            <span class="dot">·</span><span class="age" title="${esc(fullDate(ts))}">${ago(ts)}</span>
            <span class="dot">·</span><span class="source">via ${esc(item.source)}</span>
            ${item.tags.map((tag) => `<span class="tag">#${esc(tag)}</span>`).join('')}
          </div>
          ${item.content && item.title ? `<p class="item-summary">${esc(item.content)}</p>` : ''}
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
      <button class="btn btn-sm" data-stash-action="edit">${icon('text')}Edit</button>
      <button class="btn btn-sm" data-stash-action="delete">${icon('trash')}Delete</button>
      <button class="btn btn-sm" data-stash-action="close">${icon('x')}Close</button>
    </div>
    <div class="reader-body stash-body">
      ${item.imagePath ? `<a href="${esc(item.imagePath)}" target="_blank" rel="noopener"><img src="${esc(item.imagePath)}" alt=""></a>` : ''}
      ${item.content ? `<div class="stash-text">${esc(item.content)}</div>` : ''}
      ${linksHTML(item)}
    </div>
    <div class="stash-tags">${tags}<button type="button" class="btn btn-sm" data-stash-action="edit">${icon('tag')}Edit tags</button></div>`;
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
}

/** Reloads stash counts and tags for the sidebar, header and tag chips. */
export async function refreshStashCounts() {
  const [summary, tags] = await Promise.all([api('GET', '/api/stash/summary'), api('GET', '/api/tags')]);
  state.stash.summary = summary;
  state.stash.tags = tags;
  renderNav();
  renderHeader();
  if (state.route.scope !== 'stash') return;
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

async function editItem(item) {
  let dialogEl = null;
  const updated = await modal({
    title: 'Edit',
    confirmText: 'Save',
    html: `
      <label>Title<input type="text" name="title" value="${esc(item.title || '')}" maxlength="1000" autocomplete="off"></label>
      <label>Notes<textarea name="content" rows="4">${esc(item.content || '')}</textarea></label>
      <div class="field-group"><span class="field-label">Links <small>(the first is the primary link)</small></span>${linkRowsHTML(item.links)}</div>
      <label><span>Tags <small>(separate with commas)</small></span><input type="text" name="tags" value="${esc(item.tags.join(', '))}" placeholder="reading, later" autocomplete="off"></label>`,
    onOpen: (dialog) => {
      dialogEl = dialog;
      wireLinkRows(dialog);
    },
    onSubmit: (fd) => api('PATCH', `/api/items/${item.id}`, {
      title: (fd.get('title') || '').trim() || null,
      content: fd.get('content') || null,
      links: collectLinks(dialogEl),
      tags: fd.get('tags') || '',
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
      <label>Tags (optional)<input type="text" name="tags" placeholder="reading, later" autocomplete="off"></label>`,
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
    const item = state.stash.items?.byId.get(Number(e.target.closest('.item')?.dataset.id));
    if (!item) return;
    switch (action) {
      case 'open': openItem(item.id); break;
      case 'close': closeStashItem(); break;
      case 'review': toggleReviewed(item); break;
      case 'archive': toggleArchived(item); break;
      case 'edit': editItem(item); break;
      case 'delete': deleteItem(item); break;
    }
  });

  let searchTimer = null;
  els.stash.addEventListener('input', (e) => {
    if (!e.target.matches('[data-stash-search]')) return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.stash.query = e.target.value.trim();
      reloadItems();
    }, 300);
  });

  els.content.addEventListener('scroll', () => {
    if (state.route.scope !== 'stash') return;
    const c = els.content;
    if (c.scrollTop + c.clientHeight > c.scrollHeight - 800) loadMoreItems();
  }, { passive: true });
}
