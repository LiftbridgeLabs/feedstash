/* The article list: paging, reading inline, read/starred state, and mark-as-read while scrolling. */

import { markScope } from './actions.js';
import { api } from './api.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { sanitize } from './sanitize.js';
import { scheduleNavRender } from './sidebar.js';
import { stashArticle } from './stash.js';
import { ARTICLE_SCOPES, els, feedById, newList, state, unreadFor } from './state.js';
import { $, $$, ago, esc, favicon, fullDate } from './util.js';

const PAGE_SIZE = 40;

export function resetList() {
  els.newBanner.hidden = true;
  state.list = newList();
  state.openId = null;
  state.activeId = null;
  els.articles.innerHTML = '';
  els.listEnd.className = 'list-end';
  els.listEnd.innerHTML = '';
  els.content.scrollTop = 0;
  loadMore();
}

export async function loadMore() {
  const list = state.list;
  if (list.loading || list.done || !ARTICLE_SCOPES.has(state.route.scope)) return;
  list.loading = true;
  const { scope, id } = state.route;
  const params = new URLSearchParams({
    scope,
    unread_only: state.prefs.unreadOnly,
    order: state.prefs.order,
    limit: PAGE_SIZE,
  });
  if (id != null) params.set('id', id);
  if (list.cursor) params.set('cursor', list.cursor);
  if (list.maxId != null) params.set('max_id', list.maxId);
  if (!list.articles.length) els.listEnd.innerHTML = '<div class="muted">Loading…</div>';

  let res;
  try {
    res = await api('GET', `/api/articles?${params}`);
  } catch (err) {
    if (list !== state.list) return;
    list.loading = false;
    els.listEnd.innerHTML = `<div class="muted">${esc(err.message)}</div>
      <p><button class="btn btn-sm" data-action="retry">Try again</button></p>`;
    return;
  }
  if (list !== state.list) return; // the view changed while we were loading

  list.loading = false;
  list.maxId ??= res.max_id;
  list.cursor = res.next_cursor;
  list.done = !res.next_cursor;
  const html = res.articles
    .map((a) => {
      list.byId.set(a.id, a);
      list.articles.push(a);
      return articleHTML(a);
    })
    .join('');
  els.articles.insertAdjacentHTML('beforeend', html);
  renderListEnd();
  checkScroll();
}

export function renderListEnd() {
  const list = state.list;
  const end = els.listEnd;
  if (!list.done) {
    end.className = 'list-end';
    end.innerHTML = '<div class="muted">Loading…</div>';
    return;
  }
  const { scope, id } = state.route;
  const empty = !list.articles.length;
  let title;
  let sub = '';
  if (scope === 'starred') {
    title = empty ? 'Nothing saved for later' : "That's everything you saved";
    if (empty) sub = 'Star an article (or press s) to keep it here.';
  } else if (empty) {
    title = state.prefs.unreadOnly ? "You're all caught up" : 'No articles yet';
    sub = state.prefs.unreadOnly ? 'No unread articles here.' : '';
  } else {
    title = "You've reached the end";
  }
  const unread = scope === 'starred' ? 0 : unreadFor(scope, id);
  end.className = `list-end done${empty ? ' empty' : ''}`;
  end.innerHTML = `${icon('circle-check')}<div class="big">${esc(title)}</div><div>${esc(sub)}</div>
    ${unread && !empty ? `<p><button class="btn btn-sm" data-action="mark-all">${icon('check')}Mark all as read</button></p>` : ''}`;
}

function articleHTML(a) {
  const author = a.author ? `<span class="dot">·</span><span class="author">${esc(a.author)}</span>` : '';
  const starFlag = a.starred ? `<span class="star-flag" title="Saved for later">${icon('star', true)}</span>` : '';
  return `
    <article class="item ${a.read ? 'read' : ''} ${state.activeId === a.id ? 'active' : ''}" data-id="${a.id}">
      <div class="item-row" data-action="open">
        ${a.image ? `<img class="thumb" src="${esc(a.image)}" alt="" loading="lazy">` : ''}
        <div class="item-main">
          <h2 class="item-title">${esc(a.title)}</h2>
          <div class="item-meta">
            <img src="${esc(favicon(a))}" alt="" loading="lazy">
            <span class="feed-name">${esc(a.feed_title)}</span>${author}
            <span class="dot">·</span><span class="age" title="${esc(fullDate(a.published_at))}">${ago(a.published_at)}</span>
            ${starFlag}
          </div>
          ${a.summary ? `<p class="item-summary">${esc(a.summary)}</p>` : ''}
        </div>
        <span class="age-right" title="${esc(fullDate(a.published_at))}">${ago(a.published_at)}</span>
        <div class="item-tools">
          <button class="icon-btn ${a.starred ? 'on' : ''}" data-action="star" title="${a.starred ? 'Remove from Read later' : 'Read later'} (s)">${icon('star', a.starred)}</button>
          <button class="icon-btn" data-action="toggle-read" title="${a.read ? 'Mark as unread' : 'Mark as read'} (m)">${icon(a.read ? 'circle' : 'check')}</button>
        </div>
      </div>
    </article>`;
}

function readerBar(a) {
  return `
    <button class="btn btn-sm" data-action="star">${icon('star', a.starred)}${a.starred ? 'Saved' : 'Read later'}</button>
    <button class="btn btn-sm" data-action="stash" title="Save to stash (b)">${icon('inbox')}Save to stash</button>
    <button class="btn btn-sm" data-action="toggle-read">${icon(a.read ? 'circle' : 'check')}${a.read ? 'Keep unread' : 'Mark as read'}</button>
    ${a.url ? `<a class="btn btn-sm" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${icon('external')}Visit website</a>` : ''}
    <button class="btn btn-sm" data-action="close">${icon('x')}Close</button>`;
}

export const itemEl = (id) => els.articles.querySelector(`.item[data-id="${id}"]`);

function updateItem(a) {
  const el = itemEl(a.id);
  if (!el) return;
  el.classList.toggle('read', a.read);
  const tmp = document.createElement('div');
  tmp.innerHTML = articleHTML(a);
  el.querySelector('.item-row').replaceWith(tmp.querySelector('.item-row'));
  $$('[data-bar]', el).forEach((bar) => { bar.innerHTML = readerBar(a); });
}

export function setActive(id) {
  if (state.activeId === id) return;
  itemEl(state.activeId)?.classList.remove('active');
  state.activeId = id;
  itemEl(id)?.classList.add('active');
}

function scrollToTop(el) {
  els.content.scrollTop += el.getBoundingClientRect().top - els.content.getBoundingClientRect().top;
}

export function scrollIntoViewIfNeeded(el) {
  if (!el) return;
  const box = els.content.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  if (r.top < box.top) els.content.scrollTop += r.top - box.top;
  else if (r.bottom > box.bottom) els.content.scrollTop += Math.min(r.bottom - box.bottom, r.top - box.top);
}

/* ---- reading inline */

export async function openArticle(id) {
  const a = state.list.byId.get(id);
  const el = itemEl(id);
  if (!a || !el) return;
  if (state.openId === id) return;
  closeArticle(false);

  state.openId = id;
  setActive(id);
  el.classList.add('open');
  const reader = document.createElement('div');
  reader.className = 'reader';
  const title = a.url
    ? `<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>`
    : esc(a.title);
  reader.innerHTML = `
    <h1 class="reader-title">${title}</h1>
    <div class="reader-meta">
      <img src="${esc(favicon(a))}" alt=""><a href="#/feed/${a.feed_id}">${esc(a.feed_title)}</a>
      ${a.author ? `<span>·</span><span>${esc(a.author)}</span>` : ''}
      <span>·</span><span>${esc(fullDate(a.published_at))}</span>
    </div>
    <div class="reader-bar" data-bar></div>
    <div class="reader-body"><div class="reader-loading">Loading…</div></div>
    <div class="reader-foot" data-bar></div>`;
  el.append(reader);
  scrollToTop(el);

  if (!a.read) setRead(a, true);
  else updateItem(a);

  const body = $('.reader-body', reader);
  try {
    if (a.content === undefined) a.content = (await api('GET', `/api/articles/${id}`)).content || '';
    if (state.openId !== id) return;
    const html = a.content || `<p>${esc(a.summary || 'This article has no content in the feed.')}</p>`;
    body.replaceChildren(sanitize(html));
  } catch (err) {
    body.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

export function closeArticle(scrollBack = true) {
  const id = state.openId;
  if (id == null) return;
  state.openId = null;
  const el = itemEl(id);
  if (!el) return;
  el.classList.remove('open');
  $('.reader', el)?.remove();
  if (scrollBack) scrollIntoViewIfNeeded(el);
}

export function toggleArticle(id) {
  if (state.openId === id) closeArticle();
  else openArticle(id);
}

/* ---- read & starred state: applied locally at once, sent to the server in batches */

const pendingRead = new Set();
const pendingUnread = new Set();
let flushTimer = null;

export function setRead(a, read) {
  if (a.read === read) return;
  a.read = read;
  const feed = feedById(a.feed_id);
  if (feed) feed.unread = Math.max(0, feed.unread + (read ? -1 : 1));
  (read ? pendingUnread : pendingRead).delete(a.id);
  (read ? pendingRead : pendingUnread).add(a.id);
  updateItem(a);
  scheduleNavRender();
  if (!flushTimer) flushTimer = setTimeout(flushMarks, 800);
}

export async function flushMarks(keepalive = false) {
  clearTimeout(flushTimer);
  flushTimer = null;
  for (const [read, pending, other] of [[true, pendingRead, pendingUnread], [false, pendingUnread, pendingRead]]) {
    if (!pending.size) continue;
    const ids = [...pending];
    pending.clear();
    try {
      await api('POST', '/api/articles/mark', { ids, read }, { keepalive });
    } catch (err) {
      ids.filter((i) => !other.has(i)).forEach((i) => pending.add(i));
      if (!keepalive) {
        toast(`Couldn't save read state: ${err.message}`, { error: true });
        if (!flushTimer) flushTimer = setTimeout(flushMarks, 5000);
      }
    }
  }
}

export function toggleRead(a) {
  const read = !a.read;
  a.keepUnread = !read; // don't let scroll-marking undo an explicit "keep unread"
  setRead(a, read);
}

export async function toggleStar(a) {
  const starred = !a.starred;
  const apply = (value) => {
    a.starred = value;
    state.tree.starred_count = Math.max(0, state.tree.starred_count + (value ? 1 : -1));
    updateItem(a);
    scheduleNavRender();
  };
  apply(starred);
  try {
    await api('POST', `/api/articles/${a.id}/star`, { starred });
  } catch (err) {
    apply(!starred);
    toast(err.message, { error: true });
  }
}

/* ---- scrolling: mark items read once they scroll off the top, and load more near the bottom */

let scrollQueued = false;
function onScroll() {
  if (scrollQueued) return;
  scrollQueued = true;
  requestAnimationFrame(() => {
    scrollQueued = false;
    checkScroll();
  });
}

function checkScroll() {
  if (!ARTICLE_SCOPES.has(state.route.scope)) return;
  const list = state.list;
  const top = els.content.getBoundingClientRect().top;
  const items = els.articles.children;
  while (list.scanIndex < items.length) {
    const el = items[list.scanIndex];
    if (el.getBoundingClientRect().bottom > top + 1) break;
    const a = list.byId.get(Number(el.dataset.id));
    if (state.prefs.markOnScroll && a && !a.read && !a.keepUnread) setRead(a, true);
    list.scanIndex++;
  }
  const c = els.content;
  if (!list.done && !list.loading && c.scrollTop + c.clientHeight > c.scrollHeight - 1500) loadMore();
}

export function wireList() {
  els.content.addEventListener('scroll', onScroll, { passive: true });

  els.articles.addEventListener('click', (e) => {
    const item = e.target.closest('.item');
    const a = item && state.list.byId.get(Number(item.dataset.id));
    if (!a) return;
    const action = e.target.closest('[data-action]')?.dataset.action;
    if (!action) return;
    setActive(a.id);
    switch (action) {
      case 'open':
        if ((e.ctrlKey || e.metaKey) && a.url) {
          window.open(a.url, '_blank', 'noopener');
          setRead(a, true);
        } else {
          toggleArticle(a.id);
        }
        break;
      case 'close': closeArticle(); break;
      case 'star': toggleStar(a); break;
      case 'toggle-read': toggleRead(a); break;
      case 'stash': stashArticle(a); break;
    }
  });

  els.listEnd.addEventListener('click', (e) => {
    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action === 'retry') loadMore();
    if (action === 'mark-all') markScope(state.route.scope, state.route.id, null);
  });

  // Hide article thumbnails that fail to load; swap missing favicons for the app icon.
  document.addEventListener('error', (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement)) return;
    if (img.classList.contains('thumb')) img.remove();
    else if (img.src.includes('/s2/favicons') && !img.dataset.fallback) {
      img.dataset.fallback = '1';
      img.src = '/static/icon.svg';
    }
  }, true);
}
