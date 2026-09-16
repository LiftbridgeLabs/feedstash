/* Settings → Stash rules: what happens to something new when it lands in your stash. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { loadTree } from './sidebar.js';
import { folderOptionsHTML, TYPE_LABELS } from './stash.js';
import { feedById, ITEM_TYPES, stashFolderById, state } from './state.js';
import { $, esc, plural } from './util.js';

const FIELDS = [
  ['domain', 'Website is'],
  ['url', 'Address contains'],
  ['title', 'Title contains'],
  ['text', 'Title or notes contain'],
  ['feed', 'Came from feed'],
  ['type', 'Kind is'],
];
const FIELD_LABELS = Object.fromEntries(FIELDS);

export function rulesSectionHTML() {
  return `
    <h3>Stash rules</h3>
    <div class="org-head">
      <p class="muted">Rules run on everything new that reaches your stash, wherever it came from. Bulk imports skip
        them, since an import already says where its links go.</p>
      <div class="org-actions">
        <button class="btn btn-sm btn-primary" data-rules="new">${icon('plus')}New rule</button>
        <button class="btn btn-sm" data-rules="apply">Run on everything saved</button>
      </div>
    </div>
    <div data-rule-list><p class="muted">Loading…</p></div>`;
}

function whatItLooksFor(rule) {
  if (rule.field === 'feed') return feedById(Number(rule.value))?.title || 'a feed you no longer follow';
  if (rule.field === 'type') return TYPE_LABELS[rule.value] || rule.value;
  return rule.value;
}

function whatItDoes(rule) {
  const chips = [];
  if (rule.addTag) chips.push(`#${esc(rule.addTag)}`);
  if (rule.folderId) chips.push(`${esc(stashFolderById(rule.folderId)?.name || 'a deleted folder')}`);
  if (rule.markReviewed) chips.push('Mark reviewed');
  if (rule.archive) chips.push('Archive');
  return chips.map((text) => `<span class="chip">${text}</span>`).join('');
}

export async function loadRules(root) {
  const box = $('[data-rule-list]', root);
  if (!box) return;
  try {
    const rules = await api('GET', '/api/stash/rules');
    if (!box.isConnected) return;
    box.innerHTML = rules.length
      ? `<div class="table-wrap"><table class="org-table">
          <thead><tr><th>When</th><th>Then</th><th></th></tr></thead>
          <tbody>${rules.map((rule) => `<tr>
            <td><span class="rule-when">${esc(FIELD_LABELS[rule.field] || rule.field)}</span> ${esc(whatItLooksFor(rule))}</td>
            <td><div class="rule-then">${whatItDoes(rule)}</div></td>
            <td class="row-actions"><button class="btn btn-sm" data-rules="delete" data-id="${rule.id}">Delete</button></td>
          </tr>`).join('')}</tbody></table></div>`
      : '<p class="muted">No rules yet. Rules can tag what you save, file it in a folder, or get it out of the Inbox.</p>';
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

function ruleFormHTML() {
  const feeds = state.tree.feeds.map((f) => `<option value="${f.id}">${esc(f.title)}</option>`).join('');
  const types = ITEM_TYPES.map((type) => `<option value="${type}">${TYPE_LABELS[type]}</option>`).join('');
  return `
    <label>When<select name="field">${FIELDS.map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></label>
    <label data-value-for="domain url title text">This
      <input type="text" name="text" placeholder="example.com" maxlength="500" autocomplete="off"
        data-1p-ignore data-lpignore="true" data-form-type="other"></label>
    <label data-value-for="feed">This feed<select name="feed">${feeds || '<option value="">You follow no feeds yet</option>'}</select></label>
    <label data-value-for="type">This kind<select name="type">${types}</select></label>
    <div class="field-group"><span class="field-label">Then</span>
      <label>Add tag <small>(optional)</small><input type="text" name="addTag" maxlength="50" autocomplete="off"></label>
      <label>File in folder<select name="folderId">${folderOptionsHTML(null)}</select></label>
      <label class="check"><input type="checkbox" name="markReviewed"> Mark reviewed (skip the Inbox)</label>
      <label class="check"><input type="checkbox" name="archive"> Archive it</label>
    </div>`;
}

async function newRule(root) {
  const created = await modal({
    title: 'New stash rule',
    confirmText: 'Add rule',
    html: ruleFormHTML(),
    onOpen: (dialog) => {
      const field = $('select[name=field]', dialog);
      const sync = () => dialog.querySelectorAll('[data-value-for]').forEach((el) => {
        el.hidden = !el.dataset.valueFor.split(' ').includes(field.value);
      });
      field.addEventListener('change', sync);
      sync();
    },
    onSubmit: (fd) => {
      const field = fd.get('field');
      const value = field === 'feed' ? fd.get('feed') : field === 'type' ? fd.get('type') : (fd.get('text') || '').trim();
      if (!value) throw new Error('Say what the rule looks for');
      return api('POST', '/api/stash/rules', {
        field,
        value,
        addTag: (fd.get('addTag') || '').trim() || null,
        folderId: fd.get('folderId') ? Number(fd.get('folderId')) : null,
        markReviewed: fd.get('markReviewed') === 'on',
        archive: fd.get('archive') === 'on',
      });
    },
  });
  if (!created || created === true) return;
  loadRules(root);
  toast('Rule added. It runs on everything saved from now on.');
}

async function deleteRule(root, id) {
  try {
    await api('DELETE', `/api/stash/rules/${id}`);
    loadRules(root);
    toast('Rule deleted');
  } catch (err) {
    toast(err.message, { error: true });
  }
}

async function applyRules(button) {
  button.disabled = true;
  try {
    const { changed } = await api('POST', '/api/stash/rules/apply');
    await loadTree();
    toast(changed ? `${plural(changed, 'item')} updated` : 'Nothing needed changing');
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    button.disabled = false;
  }
}

export function wireRules(root) {
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-rules]');
    if (!button) return;
    switch (button.dataset.rules) {
      case 'new': newRule(root); break;
      case 'delete': deleteRule(root, Number(button.dataset.id)); break;
      case 'apply': applyRules(button); break;
    }
  });
}
