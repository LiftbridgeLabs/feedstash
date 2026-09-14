/* DOM helpers, formatting and local storage. No app state. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);

export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
export const byName = (a, b) => a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });

export function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function saveJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
}

export function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
export const agoLong = (ts) => (ago(ts) === 'now' ? 'just now' : `${ago(ts)} ago`);
export const fullDate = (ts) => new Date(ts * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
export const hoursLabel = (h) => ({ 12: '12 hours', 24: '1 day', 168: '1 week' }[h] || `${h} hours`);

export function favicon(item) {
  try {
    const host = new URL(item.site_url || item.url).hostname;
    return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`;
  } catch {
    return '/static/icon.svg';
  }
}
