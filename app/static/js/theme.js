/* Light, dark or automatic, in a choice of color schemes. The choice belongs to this browser (localStorage),
   and is applied to <html> as data-mode and data-scheme; style.css holds the palettes. */

import { loadJSON, saveJSON } from './util.js';

export const MODES = [['auto', 'Match my system'], ['light', 'Light'], ['dark', 'Dark']];
export const SCHEMES = [
  ['feedstash', 'FeedStash', '#1f9d55'],
  ['ocean', 'Ocean', '#2b7fd4'],
  ['plum', 'Plum', '#7c4ddc'],
  ['ember', 'Ember', '#cc5b22'],
  ['sepia', 'Sepia', '#9a6b34'],
  ['nord', 'Nord', '#5e81ac'],
];

const KEY = 'reader.theme';
const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

export const theme = { mode: 'auto', scheme: 'feedstash', ...loadJSON(KEY, {}) };

export function applyTheme() {
  const root = document.documentElement;
  root.dataset.mode = theme.mode === 'auto' ? (systemDark.matches ? 'dark' : 'light') : theme.mode;
  root.dataset.scheme = theme.scheme;
}

export function setTheme(changes) {
  Object.assign(theme, changes);
  saveJSON(KEY, theme);
  applyTheme();
}

systemDark.addEventListener('change', () => {
  if (theme.mode === 'auto') applyTheme();
});
