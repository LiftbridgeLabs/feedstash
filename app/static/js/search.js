/* One search box in the toolbar: it searches articles while you're in the feeds, and saved items in the stash. */

import { resetList } from './articles.js';
import { searchStash } from './stash.js';
import { state } from './state.js';
import { $ } from './util.js';

const box = () => $('#toolbar-search');

function updateMarkButton() {
  // Marking as read works on a whole feed or folder, so it's paused while a search narrows the list.
  const mark = $('[data-dropdown="mark-menu"]');
  if (mark) mark.disabled = Boolean(state.articleQuery);
}

/** Shows the box on the panels that can search, carrying that panel's own search text. */
export function syncSearchBox(panel) {
  const input = box();
  if (!input) return;
  const stash = panel === 'stash';
  input.hidden = !(stash || panel === 'articles');
  input.placeholder = stash ? 'Search your stash' : 'Search articles';
  input.setAttribute('aria-label', input.placeholder);
  input.value = stash ? state.stash.query : state.articleQuery;
  updateMarkButton();
}

export function focusSearch() {
  const input = box();
  if (input && !input.hidden) {
    input.focus();
    input.select();
  }
}

export function wireSearch() {
  const input = box();
  if (!input) return;
  let timer = null;
  input.addEventListener('input', (e) => {
    const value = e.target.value.trim();
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (state.route.scope === 'stash') {
        if (value === state.stash.query) return;
        state.stash.query = value;
        searchStash();
      } else {
        if (value === state.articleQuery) return;
        state.articleQuery = value;
        updateMarkButton();
        resetList();
      }
    }, 300);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !e.target.value) return;
    e.stopPropagation();
    e.target.value = '';
    e.target.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
