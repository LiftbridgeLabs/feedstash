/* Hash routes:
   home     #/  (All articles, or Everything saved when no feeds are followed)
   feeds    #/all  #/starred  #/uncategorized  #/folder/3  #/feed/7  #/organize
   stash    #/stash/all (inbox = to review, link, snippet = notes, screenshot, email, archived)  #/stash/tag/<name>
            #/stash/folder/2 (a stash folder)  #/stash/list/5 (a smart list)
   other    #/settings */

import { resetList } from './articles.js';
import { closeMenus } from './menus.js';
import { showOrganize } from './organize.js';
import { syncSearchBox } from './search.js';
import { showSettings } from './settings.js';
import { renderHeader, renderNav } from './sidebar.js';
import { showStash } from './stash.js';
import { ARTICLE_SCOPES, els, feedById, folderById, newList, showsFeeds, showsStash, STASH_VIEWS, state } from './state.js';
import { $ } from './util.js';

const PANELS = { organize: 'organize', stash: 'stash', settings: 'settings' };

function parseRoute() {
  const [scope, rawId, extra] = location.hash.replace(/^#\/?/, '').split('/');
  if (scope === 'folder' || scope === 'feed') {
    const id = parseInt(rawId, 10);
    if (id > 0) return { scope, id };
  }
  if (scope === 'stash') {
    if (rawId === 'tag' && extra) {
      try {
        return { scope, id: `tag:${decodeURIComponent(extra)}` };
      } catch { /* malformed escape: fall through to Everything saved */ }
    }
    if ((rawId === 'folder' || rawId === 'list') && extra) {
      const id = parseInt(extra, 10);
      if (id > 0) return { scope, id: `${rawId}:${id}` };
    }
    return { scope, id: Object.hasOwn(STASH_VIEWS, rawId ?? '') ? rawId : 'all' };
  }
  if (['starred', 'uncategorized', 'organize', 'settings'].includes(scope)) return { scope, id: null };
  return { scope: 'all', id: null };
}

export function navigate(hash) {
  if (location.hash === hash) applyRoute();
  else location.hash = hash;
}

/** Shows one content panel (articles, organize, stash or settings) and the toolbar actions that go with it. */
function showPanel(name) {
  els.articles.hidden = name !== 'articles';
  els.listEnd.hidden = name !== 'articles';
  els.organize.hidden = name !== 'organize';
  els.stash.hidden = name !== 'stash';
  els.settings.hidden = name !== 'settings';
  $('#list-actions').hidden = name !== 'articles';
  $('#stash-actions').hidden = name !== 'stash';
  els.newBanner.hidden = true; // whatever it was announcing belongs to the view being left
  if (name !== 'articles') {
    state.list = newList(); // cancels in-flight article loads
    state.openId = null;
  }
  if (name !== 'stash') {
    els.stash.innerHTML = '';
    state.stash.items = null; // cancels in-flight stash loads
  }
  syncSearchBox(name);
  els.content.scrollTop = 0;
}

export function applyRoute() {
  // Home (the brand link, or no hash) is All articles, unless nothing is followed yet: then it's the stash.
  if (/^#?\/?$/.test(location.hash) && showsStash() && (!state.tree.feeds.length || !showsFeeds())) {
    navigate('#/stash/all');
    return;
  }
  const route = parseRoute();
  // Someone who only uses one half of the app never lands in the other (an old link, a bookmark).
  if (!showsFeeds() && (ARTICLE_SCOPES.has(route.scope) || route.scope === 'organize')) {
    navigate('#/stash/all');
    return;
  }
  if (!showsStash() && route.scope === 'stash') {
    navigate('#/all');
    return;
  }
  const missing =
    (route.scope === 'folder' && !folderById(route.id)) ||
    (route.scope === 'feed' && !feedById(route.id));
  if (missing) {
    navigate('#/all');
    return;
  }
  state.route = route;
  document.body.classList.remove('nav-open');
  closeMenus();
  renderNav();
  renderHeader();

  const panel = PANELS[route.scope] || 'articles';
  showPanel(panel);
  if (panel === 'organize') showOrganize();
  else if (panel === 'stash') showStash();
  else if (panel === 'settings') showSettings();
  else resetList();
}
