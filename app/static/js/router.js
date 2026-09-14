/* Hash routes: #/all, #/starred, #/uncategorized, #/folder/3, #/feed/7, #/organize */

import { resetList } from './articles.js';
import { closeMenus } from './menus.js';
import { showOrganize } from './organize.js';
import { renderHeader, renderNav } from './sidebar.js';
import { els, feedById, folderById, state } from './state.js';

function parseRoute() {
  const [scope, rawId] = location.hash.replace(/^#\/?/, '').split('/');
  if (scope === 'folder' || scope === 'feed') {
    const id = parseInt(rawId, 10);
    if (id > 0) return { scope, id };
  }
  if (['starred', 'uncategorized', 'organize'].includes(scope)) return { scope, id: null };
  return { scope: 'all', id: null };
}

export function navigate(hash) {
  if (location.hash === hash) applyRoute();
  else location.hash = hash;
}

export function applyRoute() {
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
  if (route.scope === 'organize') {
    showOrganize();
  } else {
    els.organize.hidden = true;
    els.articles.hidden = false;
    els.listEnd.hidden = false;
    resetList();
  }
}
