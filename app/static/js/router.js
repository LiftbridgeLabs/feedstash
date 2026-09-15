/* Hash routes:
   home     #/  (All articles, or the stash Inbox when no feeds are followed)
   feeds    #/all  #/starred  #/uncategorized  #/folder/3  #/feed/7  #/organize
   stash    #/stash/inbox (all, link, snippet, screenshot, email, archived)  #/stash/tag/<name>
   other    #/settings */

import { resetList } from './articles.js';
import { closeMenus } from './menus.js';
import { showOrganize } from './organize.js';
import { showSettings } from './settings.js';
import { renderHeader, renderNav } from './sidebar.js';
import { showStash } from './stash.js';
import { els, feedById, folderById, newList, STASH_VIEWS, state } from './state.js';
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
      } catch { /* malformed escape: fall through to the inbox */ }
    }
    return { scope, id: Object.hasOwn(STASH_VIEWS, rawId ?? '') ? rawId : 'inbox' };
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
  if (name !== 'articles') {
    els.newBanner.hidden = true;
    state.list = newList(); // cancels in-flight article loads
    state.openId = null;
  }
  if (name !== 'stash') {
    els.stash.innerHTML = '';
    state.stash.items = null; // cancels in-flight stash loads
  }
  els.content.scrollTop = 0;
}

export function applyRoute() {
  // Home (the brand link, or no hash) is All articles, unless nothing is followed yet: then it's the stash.
  if (/^#?\/?$/.test(location.hash) && !state.tree.feeds.length) {
    navigate('#/stash/inbox');
    return;
  }
  const route = parseRoute();
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
