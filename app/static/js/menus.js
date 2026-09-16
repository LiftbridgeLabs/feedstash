/* The toolbar (refresh, mark-as-read menu, view options) and the sidebar's ⋯ context menus. */

import {
  addFeedDialog, deleteFolder, markScope, moveFeedDialog, refresh, renameFeed, renameFolder, unfollowFeed,
} from './actions.js';
import { api } from './api.js';
import { flushMarks, resetList } from './articles.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { moveFeedBy, moveFolderBy, sortFeedsAlpha } from './ordering.js';
import { loadTree } from './sidebar.js';
import { captureDialog } from './stash.js';
import {
  deleteSmartList, deleteStashFolder, editSmartList, moveStashFolderBy, renameStashFolder,
} from './stashlists.js';
import { els, feedById, feedIdsIn, smartListById, stashFolderById, state } from './state.js';
import { $, $$, esc, saveJSON } from './util.js';

export function closeMenus() {
  els.contextMenu.hidden = true;
  $$('.dropdown .menu').forEach((m) => { m.hidden = true; });
}

const MENUS = {
  folder: folderMenuItems,
  feed: feedMenuItems,
  'stash-folder': stashFolderMenuItems,
  'smart-list': smartListMenuItems,
};

export function openContextMenu(kind, id, anchor) {
  openMenu((MENUS[kind] || feedMenuItems)(id), anchor);
}

/** Shows a little menu under `anchor`. Items are [label, onChoose, className?]. */
export function openMenu(items, anchor) {
  closeMenus();
  const menu = els.contextMenu;
  menu.innerHTML = items.map(([label, , cls], i) => `<button data-i="${i}" class="${cls || ''}">${esc(label)}</button>`).join('');
  menu.onclick = (e) => {
    const button = e.target.closest('[data-i]');
    if (!button) return;
    closeMenus();
    items[Number(button.dataset.i)][1]();
  };
  menu.hidden = false;
  const r = anchor.getBoundingClientRect();
  const w = menu.offsetWidth;
  const h = menu.offsetHeight;
  menu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
  menu.style.top = `${r.bottom + h + 8 > window.innerHeight ? Math.max(8, r.top - h - 4) : r.bottom + 4}px`;
}

function folderMenuItems(id) {
  const order = state.tree.folders.map((f) => f.id);
  const at = order.indexOf(id);
  const items = [
    ['Mark all as read', () => markScope('folder', id, null)],
    ['Rename', () => renameFolder(id)],
  ];
  if (at > 0) items.push(['Move up', () => moveFolderBy(id, -1)]);
  if (at < order.length - 1) items.push(['Move down', () => moveFolderBy(id, 1)]);
  if (feedIdsIn(id).length > 1) items.push(['Sort feeds A–Z', () => sortFeedsAlpha(id)]);
  items.push(['Delete folder', () => deleteFolder(id), 'danger']);
  return items;
}

function feedMenuItems(id) {
  const feed = feedById(id);
  const siblings = feedIdsIn(feed?.folder_id ?? null);
  const at = siblings.indexOf(id);
  const items = [
    ['Mark all as read', () => markScope('feed', id, null)],
    ['Rename', () => renameFeed(id)],
    ['Move to folder…', () => moveFeedDialog(id)],
  ];
  if (at > 0) items.push(['Move up', () => moveFeedBy(id, -1)]);
  if (at < siblings.length - 1) items.push(['Move down', () => moveFeedBy(id, 1)]);
  items.push(['Refresh now', () => refresh('feed', id)]);
  items.push([
    feed?.auto_stash ? 'Stop saving new articles to the stash' : 'Save new articles to the stash',
    () => toggleAutoStash(id),
  ]);
  if (feed?.site_url) items.push(['Open website', () => window.open(feed.site_url, '_blank', 'noopener')]);
  items.push(['Unfollow', () => unfollowFeed(id), 'danger']);
  return items;
}

/** A feed whose new articles go straight to the stash (and are marked read here). */
export async function toggleAutoStash(id) {
  const feed = feedById(id);
  if (!feed) return;
  try {
    await api('PATCH', `/api/feeds/${id}`, { auto_stash: !feed.auto_stash });
    await loadTree();
    toast(feed.auto_stash
      ? `New articles from ${feed.title} stay in the feed`
      : `New articles from ${feed.title} will go straight to your stash`);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

function stashFolderMenuItems(id) {
  const order = (state.stash.summary.folders || []).map((f) => f.id);
  const at = order.indexOf(id);
  const items = [['Rename', () => renameStashFolder(id)]];
  if (at > 0) items.push(['Move up', () => moveStashFolderBy(id, -1)]);
  if (at >= 0 && at < order.length - 1) items.push(['Move down', () => moveStashFolderBy(id, 1)]);
  items.push([`Delete folder${stashFolderById(id)?.count ? ' (keeps its items)' : ''}`, () => deleteStashFolder(id), 'danger']);
  return items;
}

function smartListMenuItems(id) {
  return [
    ['Edit', () => editSmartList(id)],
    ['Delete', () => deleteSmartList(id), 'danger'],
  ].filter(() => smartListById(id));
}

export function wireToolbar() {
  $$('[data-dropdown]').forEach((button) => {
    button.addEventListener('click', (e) => {
      e.stopPropagation();
      const menu = document.getElementById(button.dataset.dropdown);
      const wasHidden = menu.hidden;
      closeMenus();
      menu.hidden = !wasHidden;
      if (!menu.hidden && menu.id === 'view-menu') renderViewMenu();
    });
  });

  document.addEventListener('click', (e) => {
    // The buttons that open menus are exempt, or the click that opens one would close it again.
    if (!e.target.closest('.menu, [data-dropdown], [data-menu], [data-action$="-menu"]')) closeMenus();
  });
  window.addEventListener('resize', closeMenus);
  els.nav.addEventListener('scroll', () => { els.contextMenu.hidden = true; }, { passive: true });

  $('#mark-menu').addEventListener('click', (e) => {
    const button = e.target.closest('[data-mark]');
    if (!button) return;
    closeMenus();
    const hours = button.dataset.mark === 'all' ? null : Number(button.dataset.mark);
    markScope(state.route.scope, state.route.id, hours);
  });

  $('#view-menu').addEventListener('click', (e) => {
    const button = e.target.closest('[data-pref]');
    if (!button) return;
    const key = button.dataset.pref;
    let value;
    if (button.hasAttribute('data-toggle')) value = !state.prefs[key];
    else if (button.dataset.value === 'true' || button.dataset.value === 'false') value = button.dataset.value === 'true';
    else value = button.dataset.value;
    setPref(key, value);
    renderViewMenu();
  });

  $('#refresh-btn').addEventListener('click', () => refresh());
  $('#add-menu').addEventListener('click', (e) => {
    const choice = e.target.closest('[data-add]')?.dataset.add;
    if (!choice) return;
    closeMenus();
    if (choice === 'save') captureDialog();
    else addFeedDialog();
  });
  $('#capture-btn').addEventListener('click', () => captureDialog());
  $('#menu-toggle').addEventListener('click', () => document.body.classList.toggle('nav-open'));
  $('#scrim').addEventListener('click', () => document.body.classList.remove('nav-open'));
  $('#logout-btn').addEventListener('click', async () => {
    await flushMarks();
    await api('POST', '/auth/logout').catch(() => {});
    location.href = '/';
  });
}

function renderViewMenu() {
  $$('#view-menu [data-pref]').forEach((button) => {
    const value = state.prefs[button.dataset.pref];
    const on = button.hasAttribute('data-toggle') ? Boolean(value) : String(value) === button.dataset.value;
    let check = button.querySelector('.check');
    if (!check) {
      check = document.createElement('span');
      check.className = 'check';
      button.prepend(check);
    }
    check.innerHTML = on ? icon('check') : '';
  });
}

export function setPref(key, value) {
  if (state.prefs[key] === value) return;
  state.prefs[key] = value;
  saveJSON('reader.prefs', state.prefs);
  if (key === 'layout') applyLayout();
  if (key === 'density') applyDensity();
  if (key === 'order' || key === 'unreadOnly') resetList();
}

export function applyLayout() {
  els.articles.classList.toggle('layout-titles', state.prefs.layout === 'titles');
}

/** How much room each row in the lists gets: compact, standard or comfortable. */
export function applyDensity() {
  document.documentElement.dataset.density = state.prefs.density;
}
