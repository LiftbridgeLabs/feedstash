/* Settings → Tags: every tag with a checkbox and its count. Check two or more and merge them into one (every item with
   any of them gets the merged tag), or check one and rename it. Look-alike groups are offered to check in one click. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { state } from './state.js';
import { lookAlikeGroups } from './tagpicker.js';
import { $, $$, esc } from './util.js';

const checked = new Set();
let tags = [];

export function tagsSectionHTML() {
  return `
    <h3 data-tags-heading>Tags</h3>
    <p class="muted">Check two or more tags and merge them into one: every item with any of them gets the merged tag.
      Check one to rename it.</p>
    <div data-tag-settings><p class="muted">Loading…</p></div>`;
}

export async function loadTagSettings(root) {
  const box = $('[data-tag-settings]', root);
  if (!box) return;
  try {
    tags = (await api('GET', '/api/tags')).filter((tag) => tag.count);
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  state.stash.tags = tags;
  for (const name of [...checked]) if (!tags.some((tag) => tag.name === name)) checked.delete(name);
  render(box);
}

function render(box) {
  if (!tags.length) {
    box.innerHTML = '<p class="muted">No tags yet. Tags you add to saved items show up here.</p>';
    return;
  }
  const filter = $('[data-tag-filter]', box)?.value || '';
  const groups = lookAlikeGroups(tags);
  box.innerHTML = `
    ${groups.length ? `<div class="tag-lookalikes"><span class="muted">Look alike:</span>
      ${groups.map(({ into, from }) => {
        const names = [into, ...from].map((tag) => tag.name);
        return `<button type="button" class="btn btn-sm" data-check-group="${esc(JSON.stringify(names))}" title="Check these">${names.map((n) => `#${esc(n)}`).join(' · ')}</button>`;
      }).join('')}</div>` : ''}
    <div class="tag-settings-bar">
      <input type="search" placeholder="Find a tag" value="${esc(filter)}" data-tag-filter aria-label="Find a tag">
      <span class="muted" data-checked-count></span>
      <button type="button" class="btn btn-sm btn-primary" data-tag-action="merge">Merge into…</button>
      <button type="button" class="btn btn-sm" data-tag-action="rename">Rename…</button>
      <button type="button" class="btn btn-sm" data-tag-action="clear">Clear</button>
    </div>
    <div class="tag-settings-list">${tags.map((tag) => `
      <label class="tag-check" data-tag-row="${esc(tag.name)}"><input type="checkbox" data-tag-name="${esc(tag.name)}" ${checked.has(tag.name) ? 'checked' : ''}>
        <span>#${esc(tag.name)}</span> <small>${tag.count}</small></label>`).join('')}
    </div>`;
  applyFilter(box);
  updateBar(box);
}

function applyFilter(box) {
  const word = ($('[data-tag-filter]', box)?.value || '').trim().replace(/^#+/, '').toLowerCase();
  $$('[data-tag-row]', box).forEach((row) => {
    row.hidden = Boolean(word) && !row.dataset.tagRow.includes(word) && !checked.has(row.dataset.tagRow);
  });
}

function updateBar(box) {
  const count = checked.size;
  $('[data-checked-count]', box).textContent = count ? `${count} checked` : '';
  $('[data-tag-action=merge]', box).disabled = count < 2;
  $('[data-tag-action=rename]', box).disabled = count !== 1;
  $('[data-tag-action=clear]', box).disabled = count === 0;
}

/** The checked tags, most used first: the first is the suggested name to merge into. */
function checkedTags() {
  return tags.filter((tag) => checked.has(tag.name));
}

async function mergeChecked(root) {
  const chosen = checkedTags();
  const result = await modal({
    title: `Merge ${chosen.length} tags`,
    confirmText: 'Merge',
    html: `<p>${chosen.map((tag) => `#${esc(tag.name)} <small>(${tag.count})</small>`).join(', ')}</p>
      <label>Merge into <small>(one of them, or a new name)</small>
        <input type="text" name="into" value="${esc(chosen[0].name)}" maxlength="200" autocomplete="off"></label>`,
    onSubmit: (fd) => api('POST', '/api/tags/merge', { names: chosen.map((tag) => tag.name), into: fd.get('into') || '' }),
  });
  if (!result || result === true) return;
  checked.clear();
  await loadTagSettings(root);
  toast(`Merged ${chosen.length} tags into #${result.name} (${result.items} item${result.items === 1 ? '' : 's'})`);
}

async function renameChecked(root) {
  const [tag] = checkedTags();
  const result = await modal({
    title: `Rename #${tag.name}`,
    confirmText: 'Rename',
    html: `<label>New name <small>(an existing tag's name merges the two)</small>
      <input type="text" name="name" value="${esc(tag.name)}" maxlength="200" autocomplete="off"></label>`,
    onSubmit: (fd) => api('POST', '/api/tags/rename', { name: tag.name, newName: fd.get('name') || '' }),
  });
  if (!result || result === true) return;
  checked.clear();
  await loadTagSettings(root);
  toast(result.merged ? `Merged #${tag.name} into #${result.name}` : `Renamed #${tag.name} to #${result.name}`);
}

export function wireTagSettings(root) {
  root.addEventListener('change', (e) => {
    const box = e.target.closest('[data-tag-settings]');
    const name = e.target.dataset?.tagName;
    if (!box || name == null) return;
    if (e.target.checked) checked.add(name);
    else checked.delete(name);
    updateBar(box);
  });
  root.addEventListener('input', (e) => {
    if (e.target.matches('[data-tag-filter]')) applyFilter(e.target.closest('[data-tag-settings]'));
  });
  root.addEventListener('click', (e) => {
    const box = e.target.closest('[data-tag-settings]');
    if (!box) return;
    const group = e.target.closest('[data-check-group]');
    if (group) {
      checked.clear();
      JSON.parse(group.dataset.checkGroup).forEach((name) => checked.add(name));
      render(box);
      return;
    }
    switch (e.target.closest('[data-tag-action]')?.dataset.tagAction) {
      case 'merge': mergeChecked(root); break;
      case 'rename': renameChecked(root); break;
      case 'clear': checked.clear(); render(box); break;
    }
  });
}
