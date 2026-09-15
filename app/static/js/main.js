/* Entry point: wires up the UI, loads the user and sidebar, then renders the current route. */

import { api } from './api.js';
import { wireList } from './articles.js';
import { pollForNew, showNewBanner, startAutoRefresh } from './autorefresh.js';
import { toast } from './dialogs.js';
import { hydrateIcons } from './icons.js';
import { wireKeyboard } from './keyboard.js';
import { applyLayout, openContextMenu, setPref, wireToolbar } from './menus.js';
import { wireOrganize } from './organize.js';
import { applyRoute } from './router.js';
import { wireSettings } from './settings.js';
import { loadTree, wireNav } from './sidebar.js';
import { captureDialog, stashArticle, wireStash } from './stash.js';
import { state } from './state.js';
import { $ } from './util.js';

async function init() {
  hydrateIcons();
  applyLayout();
  wireNav();
  wireToolbar();
  wireList();
  wireOrganize();
  wireStash();
  wireSettings();
  wireKeyboard();
  startAutoRefresh();

  try {
    const [me] = await Promise.all([api('GET', '/api/me'), loadTree()]);
    $('#user-name').textContent = me.name || me.email;
    $('#user-name').title = me.email;
    const { version } = state.tree;
    $('#app-version').textContent = version === 'dev' ? 'dev' : `v${version}`;
    if (me.picture) {
      $('#user-avatar').src = me.picture;
      $('#user-avatar').hidden = false;
    }
  } catch (err) {
    toast(err.message, { error: true });
    return;
  }
  window.addEventListener('hashchange', applyRoute);
  applyRoute();
}

// Handle for poking at the app from the console, and for the browser tests.
window.reader = {
  state, api, loadTree, applyRoute, setPref, openContextMenu, pollForNew, showNewBanner, captureDialog, stashArticle,
};

init();
