/* Settings → Logs (admins): how much the server logs and how much it keeps, and the latest lines to read. */

import { api } from './api.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { $, esc } from './util.js';

const LEVELS = [['info', 'Normal'], ['debug', 'Detailed (for tracking down a problem)']];
const REQUESTS = [
  ['changes', 'Saves, edits and errors'], ['errors', 'Only errors'], ['all', 'Every request'], ['none', 'None'],
];
const KEEP = [1, 2, 3, 5, 10];
const SIZES = [5, 10, 25, 50, 100];

export function logsSectionHTML() {
  return `
    <div data-logs-section hidden>
      <h3>Logs</h3>
      <p class="muted">FeedStash keeps its own log files in its data folder and starts a new one when a file gets
        too big, deleting the oldest. The container's own log only gets warnings and errors.</p>
      <div data-logs-settings><p class="muted">Loading…</p></div>
      <div class="org-head">
        <p class="muted">The latest lines, newest at the bottom.</p>
        <div class="org-actions">
          <button class="btn btn-sm" data-logs="refresh">${icon('refresh')}Refresh</button>
          <a class="btn btn-sm" href="/api/admin/logs/download" download>${icon('copy')}Download the log</a>
        </div>
      </div>
      <pre class="log-view" data-log-view></pre>
    </div>`;
}

const options = (choices, current) => choices
  .map(([value, label]) => `<option value="${esc(value)}" ${String(value) === String(current) ? 'selected' : ''}>${esc(label)}</option>`)
  .join('');

/** Shows the section (admins only) and fills it in. */
export async function loadLogs(root) {
  const section = $('[data-logs-section]', root);
  if (!section) return;
  section.hidden = false;
  let settings;
  try {
    settings = await api('GET', '/api/admin/logs/settings');
  } catch (err) {
    $('[data-logs-settings]', section).innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  $('[data-logs-settings]', section).innerHTML = `
    <div class="setting-row">
      <label for="log-level">Detail</label>
      <select id="log-level" data-log-field="level">${options(LEVELS, settings.level)}</select>
    </div>
    <div class="setting-row">
      <label for="log-requests">Requests</label>
      <select id="log-requests" data-log-field="requests">${options(REQUESTS, settings.requests)}</select>
    </div>
    <div class="setting-row">
      <label for="log-keep">Keep</label>
      <select id="log-keep" data-log-field="keep_files">${options(KEEP.map((n) => [n, n === 1 ? '1 older file' : `${n} older files`]), settings.keep_files)}</select>
    </div>
    <div class="setting-row">
      <label for="log-size">New file every</label>
      <select id="log-size" data-log-field="max_mb">${options(SIZES.map((n) => [n, `${n} MB`]), settings.max_mb)}</select>
      <p class="muted">In <code>${esc(settings.directory)}</code> inside the container. At most
        ${(settings.keep_files + 1) * settings.max_mb} MB in all.</p>
    </div>`;
  refreshLines(section);
}

async function refreshLines(section) {
  const view = $('[data-log-view]', section);
  try {
    const { lines } = await api('GET', '/api/admin/logs?lines=300');
    view.textContent = lines.length ? lines.join('\n') : 'Nothing logged yet.';
    view.scrollTop = view.scrollHeight;
  } catch (err) {
    view.textContent = err.message;
  }
}

async function save(section) {
  const value = (field) => $(`[data-log-field=${field}]`, section).value;
  try {
    await api('PUT', '/api/admin/logs/settings', {
      level: value('level'), requests: value('requests'),
      keep_files: Number(value('keep_files')), max_mb: Number(value('max_mb')),
    });
    toast('Log settings saved');
    loadLogs(section.parentElement);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireLogs(root) {
  root.addEventListener('change', (e) => {
    const section = e.target.closest('[data-logs-section]');
    if (section && e.target.matches('[data-log-field]')) save(section);
  });
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-logs]');
    if (button?.dataset.logs === 'refresh') refreshLines(button.closest('[data-logs-section]'));
  });
}
