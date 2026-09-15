/* Shared app state, key DOM elements, and read-only lookups over the sidebar tree. */

import { $, loadJSON } from './util.js';

export const els = {
  nav: $('#nav'),
  content: $('#content'),
  articles: $('#articles'),
  listEnd: $('#list-end'),
  organize: $('#organize'),
  stash: $('#stash'),
  settings: $('#settings'),
  title: $('#view-title'),
  count: $('#view-count'),
  toast: $('#toast'),
  contextMenu: $('#context-menu'),
  newBanner: $('#new-banner'),
};

/** Routes that show the article list (as opposed to the stash, organize or settings panels). */
export const ARTICLE_SCOPES = new Set(['all', 'starred', 'uncategorized', 'folder', 'feed']);

export const ITEM_TYPES = ['link', 'snippet', 'screenshot', 'email'];
export const STASH_VIEWS = {
  inbox: 'Inbox',
  all: 'Everything saved',
  link: 'Links',
  snippet: 'Snippets',
  screenshot: 'Screenshots',
  email: 'Emails',
  archived: 'Archive',
};

const PREF_DEFAULTS = { layout: 'magazine', order: 'newest', unreadOnly: true, markOnScroll: true };

export const state = {
  tree: { folders: [], feeds: [], starred_count: 0 },
  route: { scope: 'all', id: null },
  prefs: { ...PREF_DEFAULTS, ...loadJSON('reader.prefs', {}) },
  collapsed: new Set(loadJSON('reader.collapsed', [])),
  list: null,
  openId: null,
  activeId: null,
  orgFilter: '',
  stash: {
    summary: { inbox: 0, total: 0, archived: 0, by_type: {} },
    tags: [],
    query: '',
    items: null, // the loaded item list for the current stash view
    openId: null,
  },
};

/** A fresh, empty article list. Replacing state.list also cancels in-flight loads for the old one. */
export function newList() {
  return {
    articles: [],
    byId: new Map(),
    cursor: null,
    maxId: null,
    loading: false,
    done: false,
    scanIndex: 0, // every item before this index has scrolled above the viewport
  };
}
state.list = newList();

export const feedById = (id) => state.tree.feeds.find((f) => f.id === id);
export const folderById = (id) => state.tree.folders.find((f) => f.id === id);
export const sumUnread = (feeds) => feeds.reduce((n, f) => n + f.unread, 0);
export const feedIdsIn = (folderId) => state.tree.feeds.filter((f) => (f.folder_id ?? null) === folderId).map((f) => f.id);

export function feedsInScope(scope, id) {
  const { feeds } = state.tree;
  switch (scope) {
    case 'folder': return feeds.filter((f) => f.folder_id === id);
    case 'uncategorized': return feeds.filter((f) => f.folder_id == null);
    case 'feed': return feeds.filter((f) => f.id === id);
    default: return feeds;
  }
}

export function unreadFor(scope, id) {
  return scope === 'starred' ? state.tree.starred_count : sumUnread(feedsInScope(scope, id));
}

export function scopeTitle(scope, id) {
  switch (scope) {
    case 'starred': return 'Read later';
    case 'uncategorized': return 'Uncategorized';
    case 'organize': return 'Organize feeds';
    case 'settings': return 'Settings';
    case 'stash': return id?.startsWith('tag:') ? `#${id.slice(4)}` : STASH_VIEWS[id] || 'Stash';
    case 'folder': return folderById(id)?.name || 'Folder';
    case 'feed': return feedById(id)?.title || 'Feed';
    default: return 'All articles';
  }
}
