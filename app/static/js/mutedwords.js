/* Settings → Muted words: new articles holding one arrive already read, on every device. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { loadTree } from './sidebar.js';
import { feedById, folderById, state } from './state.js';
import { $, esc, plural } from './util.js';

export function mutedWordsSectionHTML() {
  return `
    <h3>Muted words</h3>
    <div class="org-head">
      <p class="muted">New articles with a muted word in the title arrive already read, on every device and app.
        Words match whole, so "AI" doesn't catch "said".</p>
      <div class="org-actions">
        <button class="btn btn-sm btn-primary" data-muted="new">${icon('plus')}Mute a word</button>
      </div>
    </div>
    <div data-muted-list><p class="muted">Loading…</p></div>`;
}

function whereLabel(word) {
  if (word.feed_id) return feedById(word.feed_id)?.title || 'A feed';
  if (word.folder_id) return folderById(word.folder_id)?.name || 'A folder';
  return 'Everywhere';
}

export async function loadMutedWords(root) {
  const box = $('[data-muted-list]', root);
  if (!box) return;
  try {
    const words = await api('GET', '/api/muted-words');
    if (!box.isConnected) return;
    box.innerHTML = words.length
      ? `<div class="table-wrap"><table class="org-table">
          <thead><tr><th>Word</th><th>Where</th><th>Looks at</th><th></th></tr></thead>
          <tbody>${words.map((word) => `<tr>
            <td>${esc(word.phrase)}</td>
            <td>${esc(whereLabel(word))}</td>
            <td>${word.title_only ? 'Titles' : 'Titles and text'}</td>
            <td class="row-actions"><button class="btn btn-sm" data-muted="delete" data-id="${word.id}">Unmute</button></td>
          </tr>`).join('')}</tbody></table></div>`
      : '<p class="muted">Nothing muted yet.</p>';
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

function wordFormHTML() {
  const folders = state.tree.folders.map((f) => `<option value="folder:${f.id}">${esc(f.name)}</option>`).join('');
  const feeds = state.tree.feeds.map((f) => `<option value="feed:${f.id}">${esc(f.title)}</option>`).join('');
  return `
    <label>Word or phrase
      <input type="text" name="phrase" placeholder="crypto" maxlength="200" autocomplete="off"
        data-1p-ignore data-lpignore="true" data-form-type="other"></label>
    <label>Where<select name="where">
      <option value="">Everywhere</option>
      ${folders ? `<optgroup label="Folders">${folders}</optgroup>` : ''}
      ${feeds ? `<optgroup label="Feeds">${feeds}</optgroup>` : ''}
    </select></label>
    <label>Look at<select name="titleOnly">
      <option value="true">Titles only</option>
      <option value="false">Titles and article text</option>
    </select></label>
    <label class="check"><input type="checkbox" name="catchUp" checked> Also mark unread articles that match as read</label>`;
}

async function muteWord(root) {
  const added = await modal({
    title: 'Mute a word',
    confirmText: 'Mute',
    html: wordFormHTML(),
    onSubmit: (fd) => {
      const phrase = (fd.get('phrase') || '').trim();
      if (!phrase) throw new Error('Type a word or phrase to mute');
      const [kind, id] = (fd.get('where') || '').split(':');
      return api('POST', '/api/muted-words', {
        phrase,
        title_only: fd.get('titleOnly') === 'true',
        folder_id: kind === 'folder' ? Number(id) : null,
        feed_id: kind === 'feed' ? Number(id) : null,
        mark_unread_read: fd.get('catchUp') === 'on',
      });
    },
  });
  if (!added || added === true) return;
  loadMutedWords(root);
  if (!added.marked) {
    toast(`Muted "${added.word.phrase}"`);
    return;
  }
  await loadTree();
  toast(`Muted "${added.word.phrase}" and marked ${plural(added.marked, 'article')} as read`, {
    action: 'Undo',
    onAction: async () => {
      const undo = await api('POST', '/api/mark-read/undo', { scope: 'all', batch: added.batch });
      await loadTree();
      toast(`Restored ${plural(undo.restored, 'article')}. "${added.word.phrase}" is still muted.`);
    },
  });
}

async function unmute(root, id) {
  try {
    await api('DELETE', `/api/muted-words/${id}`);
    loadMutedWords(root);
    toast('Unmuted. Articles already marked read stay read.');
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireMutedWords(root) {
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-muted]');
    if (!button) return;
    switch (button.dataset.muted) {
      case 'new': muteWord(root); break;
      case 'delete': unmute(root, Number(button.dataset.id)); break;
    }
  });
}
