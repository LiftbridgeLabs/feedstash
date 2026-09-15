/* Settings → Import saved links. Bookmark files (Feedly boards, browser bookmarks, Pocket, Raindrop) are read here in
   the browser; each file becomes a row where the user decides whether to import it, where its links go, and how
   they're tagged. The chosen links are sent to the server in batches. */

import { api } from './api.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { importOpml } from './organize.js';
import { refreshStashCounts } from './stash.js';
import { $, esc } from './util.js';

const BATCH_SIZE = 500;
const DESTINATIONS = { inbox: 'Inbox', saved: 'Everything saved', archive: 'Archive' };

let groups = []; // one per file: { name, fileName, links, include, destination, tag, note }
let skippedNote = ''; // what a folder import left out, shown above the plan

export function importSectionHTML() {
  return `
    <h3>Import &amp; export</h3>
    <div class="org-head">
      <p class="muted"><b>From Feedly:</b> unzip the export you downloaded from Feedly and choose that whole folder.
        Your feeds and folders come in from its OPML right away, and each board shows up below so you can decide
        where its links go. <b>Feeds</b> also come in from any OPML file, and <b>saved links</b> from bookmark HTML
        files (browser bookmarks, Pocket or Raindrop exports). Links you already have are skipped.</p>
      <div class="org-actions">
        <label class="btn btn-sm btn-primary">${icon('plus')}Feedly export folder…
          <input type="file" webkitdirectory hidden data-import-folder></label>
        <label class="btn btn-sm">Import OPML…
          <input type="file" accept=".opml,.xml,text/xml,application/xml,text/x-opml" hidden data-import-opml></label>
        <label class="btn btn-sm">Bookmark files…
          <input type="file" accept=".html,.htm,text/html" multiple hidden data-import-files></label>
        <a class="btn btn-sm" href="/api/opml/export" download>Export OPML</a>
      </div>
    </div>
    <div data-import-plan></div>`;
}

/** Everything in a Feedly export folder (or any folder): OPML files become feeds, HTML files become plan rows.
    Feedly's `read/` folder is one huge file per month of reading history, so it's left out. */
async function readFolder(root, files) {
  const pathOf = (file) => file.webkitRelativePath || file.name;
  const history = files.filter((file) => /(^|\/)read\//i.test(pathOf(file)));
  const opml = files.filter((file) => /\.opml$/i.test(file.name));
  const bookmarks = files.filter((file) => /\.html?$/i.test(file.name) && !history.includes(file));
  skippedNote = history.length
    ? `Left out the "read" folder (${history.length} files of reading history, titles only).` : '';
  if (!opml.length && !bookmarks.length) {
    toast('No OPML or bookmark HTML files in that folder', { error: true });
    return;
  }
  for (const file of opml) await importOpml(file);
  if (bookmarks.length) await readFiles(root, bookmarks);
  else renderImportPlan(root);
}

/* ---- reading bookmark files */

/** Bookmark dates are usually Unix seconds, but some exports use milliseconds or microseconds. */
function toSeconds(value) {
  let n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  while (n > 1e11) n /= 1000;
  return Math.floor(n);
}

function parseBookmarks(text, fileName) {
  const doc = new DOMParser().parseFromString(text, 'text/html');
  const heading = (doc.querySelector('h1')?.textContent || '').trim();
  const name = (heading || fileName.replace(/\.html?$/i, '')).replace(/^feedly\s*-\s*/i, '').trim() || fileName;
  const links = [];
  for (const a of doc.querySelectorAll('a[href]')) {
    const url = (a.getAttribute('href') || '').trim();
    if (!/^https?:\/\//i.test(url) || url.length > 4000) continue;
    links.push({
      url,
      title: a.textContent.trim().slice(0, 1000) || null,
      saved_at: toSeconds(a.getAttribute('add_date') || a.getAttribute('time_added')),
      tags: (a.getAttribute('tags') || '').split(',').map((tag) => tag.trim()).filter(Boolean),
    });
  }
  return { name, fileName, links };
}

/** Suggested choices for a file; the user can change all of them. */
function suggestions(name) {
  if (/^unsaved$/i.test(name)) return { include: false, destination: 'archive', tag: 'feedly unsaved', note: 'Links you removed from Feedly' };
  if (/^read in \d{4}/i.test(name)) return { include: false, destination: 'archive', tag: 'feedly read', note: 'Feedly reading history' };
  const toRead = /saved for later|read later|read it later|pocket/i.test(name);
  const generic = /^(saved for later|read later|bookmarks|pocket)$/i.test(name);
  return { include: true, destination: toRead ? 'inbox' : 'saved', tag: generic ? '' : name.toLowerCase().slice(0, 50), note: '' };
}

async function readFiles(root, files) {
  const plan = $('[data-import-plan]', root);
  if (plan) plan.innerHTML = '<p class="muted">Reading files…</p>';
  for (const file of files) {
    try {
      const parsed = parseBookmarks(await file.text(), file.name);
      if (parsed.links.length) groups.push({ ...parsed, ...suggestions(parsed.name) });
      else toast(`No links found in ${file.name}`, { error: true });
    } catch {
      toast(`Couldn't read ${file.name}`, { error: true });
    }
  }
  renderImportPlan(root);
}

/* ---- the plan table */

function monthRange(links) {
  const dates = links.map((link) => link.saved_at).filter(Boolean);
  if (!dates.length) return '';
  const month = (seconds) => new Date(seconds * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
  const first = month(Math.min(...dates));
  const last = month(Math.max(...dates));
  return first === last ? first : `${first} – ${last}`;
}

export function renderImportPlan(root) {
  const plan = $('[data-import-plan]', root);
  if (!plan) return;
  if (!groups.length) {
    plan.innerHTML = skippedNote ? `<p class="muted">${esc(skippedNote)}</p>` : '';
    return;
  }
  const total = groups.filter((group) => group.include).reduce((n, group) => n + group.links.length, 0);
  plan.innerHTML = `${skippedNote ? `<p class="muted">${esc(skippedNote)}</p>` : ''}
    <div class="table-wrap"><table class="org-table import-plan">
      <thead><tr><th>Import</th><th>File</th><th>Links</th><th>Saved</th><th>Put in</th><th>Tag</th></tr></thead>
      <tbody>${groups.map((group, index) => `<tr class="${group.include ? '' : 'excluded'}">
        <td><input type="checkbox" data-import-field="include" data-index="${index}" ${group.include ? 'checked' : ''} aria-label="Import ${esc(group.name)}"></td>
        <td>${esc(group.name)}${group.note ? `<div class="muted">${esc(group.note)}</div>` : ''}</td>
        <td>${group.links.length.toLocaleString()}</td>
        <td class="nowrap">${esc(monthRange(group.links))}</td>
        <td><select data-import-field="destination" data-index="${index}" aria-label="Where ${esc(group.name)} goes">
          ${Object.entries(DESTINATIONS).map(([value, label]) => `<option value="${value}" ${group.destination === value ? 'selected' : ''}>${label}</option>`).join('')}
        </select></td>
        <td><input type="text" data-import-field="tag" data-index="${index}" value="${esc(group.tag)}" placeholder="No tag" maxlength="50" aria-label="Tag for ${esc(group.name)}"></td>
      </tr>`).join('')}</tbody></table></div>
    <div class="import-actions">
      <button class="btn btn-primary" data-import-action="run" ${total ? '' : 'disabled'}>Import ${total.toLocaleString()} link${total === 1 ? '' : 's'}</button>
      <button class="btn" data-import-action="clear">Cancel</button>
      <span class="muted" data-import-progress></span>
    </div>`;
}

/* ---- importing */

async function runImport(root) {
  const links = groups.filter((group) => group.include).flatMap((group) => group.links.map((link) => ({
    ...link,
    tags: [...new Set([group.tag.trim(), ...link.tags].filter(Boolean))].slice(0, 20),
    reviewed: group.destination !== 'inbox',
    archived: group.destination === 'archive',
  })));
  if (!links.length) return;
  $('[data-import-action=run]', root).disabled = true;
  const progress = $('[data-import-progress]', root);
  const totals = { added: 0, already_saved: 0, invalid: 0 };
  try {
    for (let start = 0; start < links.length; start += BATCH_SIZE) {
      progress.textContent = `Importing ${Math.min(start + BATCH_SIZE, links.length).toLocaleString()} of ${links.length.toLocaleString()}…`;
      const result = await api('POST', '/api/items/import', { links: links.slice(start, start + BATCH_SIZE) });
      for (const key of Object.keys(totals)) totals[key] += result[key];
    }
  } catch (err) {
    toast(`Import stopped: ${err.message}. ${totals.added} links were added before that.`, { error: true });
    await refreshStashCounts();
    renderImportPlan(root);
    return;
  }
  groups = [];
  skippedNote = '';
  renderImportPlan(root);
  await refreshStashCounts();
  const notes = [
    totals.already_saved && `${totals.already_saved} already saved`,
    totals.invalid && `${totals.invalid} not web links`,
  ].filter(Boolean);
  toast(`Imported ${totals.added} link${totals.added === 1 ? '' : 's'}${notes.length ? ` (${notes.join(', ')})` : ''}`);
}

export function wireImport(root) {
  root.addEventListener('change', (e) => {
    if (e.target.matches('[data-import-files], [data-import-folder], [data-import-opml]')) {
      const files = [...e.target.files];
      const read = e.target.matches('[data-import-folder]') ? readFolder
        : e.target.matches('[data-import-opml]') ? (_, [file]) => importOpml(file) : readFiles;
      e.target.value = '';
      if (files.length) read(root, files);
      return;
    }
    const group = groups[Number(e.target.dataset.index)];
    if (!group) return;
    switch (e.target.dataset.importField) {
      case 'include': group.include = e.target.checked; renderImportPlan(root); break;
      case 'destination': group.destination = e.target.value; break;
      case 'tag': group.tag = e.target.value; break;
    }
  });
  root.addEventListener('input', (e) => {
    const group = groups[Number(e.target.dataset.index)];
    if (group && e.target.dataset.importField === 'tag') group.tag = e.target.value;
  });
  root.addEventListener('click', (e) => {
    const action = e.target.closest('[data-import-action]')?.dataset.importAction;
    if (action === 'run') runImport(root);
    if (action === 'clear') {
      groups = [];
      skippedNote = '';
      renderImportPlan(root);
    }
  });
}
