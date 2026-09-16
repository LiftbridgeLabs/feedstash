/* The server fetches feeds on its own schedule; the page checks every minute for what it found. */

import { api } from './api.js';
import { flushMarks, resetList } from './articles.js';
import { renderOrganize } from './organize.js';
import { loadTree } from './sidebar.js';
import { pollStashForNew, reloadItems as reloadStashItems } from './stash.js';
import { els, state } from './state.js';
import { plural } from './util.js';

const POLL_MS = 60 * 1000;
let polling = false;

export async function pollForNew() {
  if (polling || document.hidden) return;
  polling = true;
  try {
    await flushMarks();
    await loadTree();
    const list = state.list;
    const { scope, id } = state.route;
    if (scope === 'organize') {
      if (!els.organize.contains(document.activeElement)) renderOrganize();
      return;
    }
    if (scope === 'stash') {
      await pollStashForNew();
      return;
    }
    if (scope === 'starred' || list.maxId == null || list.loading) return;
    const params = new URLSearchParams({ scope, since_id: list.maxId, unread_only: state.prefs.unreadOnly });
    if (id != null) params.set('id', id);
    const { count } = await api('GET', `/api/articles/new-count?${params}`);
    if (list !== state.list || !count) return;
    // Don't shuffle the list under someone who's reading; offer a button instead.
    const idle = !list.articles.length || (els.content.scrollTop < 40 && state.openId == null);
    if (idle) resetList();
    else showNewBanner(count);
  } catch {
    // Offline or the server is restarting; try again next tick.
  } finally {
    polling = false;
  }
}

export function showNewBanner(count, noun = 'new article') {
  els.newBanner.textContent = `↑ ${plural(count, noun)}`;
  els.newBanner.hidden = false;
}

export function startAutoRefresh() {
  window.addEventListener('pagehide', () => flushMarks(true));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushMarks(true);
    else pollForNew();
  });
  els.newBanner.addEventListener('click', () => {
    if (state.route.scope === 'stash') reloadStashItems();
    else resetList();
  });
  setInterval(pollForNew, POLL_MS);
}
