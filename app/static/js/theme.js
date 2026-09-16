/* Light, dark or automatic, in a choice of color schemes. The choice belongs to this browser (localStorage),
   and is applied to <html> as data-mode and data-scheme; style.css holds the palettes. */

import { loadJSON, saveJSON } from './util.js';

export const MODES = [['auto', 'Match my system'], ['light', 'Light'], ['dark', 'Dark']];
/** [id, name, the color shown on its button]. Each repaints the whole app, not just the accent. */
export const SCHEMES = [
  ['feedstash', 'FeedStash', '#1f9d55'],
  ['slate', 'Slate', '#3d6df0'],
  ['nord', 'Nord', '#5e81ac'],
  ['solarized', 'Solarized', '#268bd2'],
  ['gruvbox', 'Gruvbox', '#af3a03'],
  ['dracula', 'Dracula', '#7b4bd8'],
  ['rose', 'Rosé', '#b4436c'],
  ['forest', 'Forest', '#2f7d4f'],
  ['sepia', 'Sepia', '#9a6b34'],
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
