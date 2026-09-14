/* Keyboard shortcuts: j/k open next/previous, n/p select, o/Enter toggle, v original, m read, s star, r refresh, A mark all. */

import { markScope, refresh } from './actions.js';
import {
  closeArticle, itemEl, loadMore, openArticle, scrollIntoViewIfNeeded, setActive, setRead, toggleArticle, toggleRead,
  toggleStar,
} from './articles.js';
import { closeMenus } from './menus.js';
import { state } from './state.js';
import { $ } from './util.js';

function step(dir, open) {
  const articles = state.list.articles;
  if (!articles.length) return;
  const current = state.openId ?? state.activeId;
  let idx = articles.findIndex((x) => x.id === current);
  idx = idx === -1 ? (dir > 0 ? 0 : -1) : idx + dir;
  if (idx < 0) return;
  if (idx >= articles.length) {
    loadMore();
    return;
  }
  const next = articles[idx];
  if (open) {
    openArticle(next.id);
  } else {
    closeArticle(false);
    setActive(next.id);
    scrollIntoViewIfNeeded(itemEl(next.id));
  }
  if (idx > articles.length - 5) loadMore();
}

export function wireKeyboard() {
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    if ($('dialog[open]') || e.target.closest('input, textarea, select, [contenteditable]')) return;
    if (e.key === 'Escape') {
      closeMenus();
      document.body.classList.remove('nav-open');
      closeArticle();
      return;
    }
    if (state.route.scope === 'organize') return;
    if (e.key === 'Enter' && e.target.closest('button, a, [tabindex]:not(#content)')) return;
    const a = state.list.byId.get(state.activeId);
    switch (e.key) {
      case 'j': step(1, true); break;
      case 'k': step(-1, true); break;
      case 'n': step(1, false); break;
      case 'p': step(-1, false); break;
      case 'o': case 'Enter': if (a) toggleArticle(a.id); break;
      case 'v':
        if (a?.url) {
          window.open(a.url, '_blank', 'noopener');
          setRead(a, true);
        }
        break;
      case 'm': if (a) toggleRead(a); break;
      case 's': if (a) toggleStar(a); break;
      case 'r': refresh(); break;
      case 'A': markScope(state.route.scope, state.route.id, null); break;
      default: return;
    }
    e.preventDefault();
  });
}
