/* Settings → You → Move to another FeedStash: download everything as one file, or bring such a file in. */

import { api } from './api.js';
import { toast } from './dialogs.js';
import { icon } from './icons.js';
import { $, esc, plural } from './util.js';

export function moveSectionHTML() {
  return `
    <div data-move-section>
      <h3>Move to another FeedStash</h3>
      <p class="muted">Download everything in your account as one file: feeds and folders, articles with what you've
        read and starred, your stash with its pictures and saved pages, smart lists, rules and muted words. Bring it
        in on any FeedStash to pick up where you left off. Bringing a file in adds to what's here: nothing is
        replaced, and what's already here isn't doubled.</p>
      <div class="org-actions">
        <a class="btn btn-sm" href="/api/account/export" download>${icon('copy')}Download everything</a>
        <button class="btn btn-sm" type="button" data-move="choose">Bring in from another FeedStash…</button>
        <input type="file" accept=".zip,application/zip" data-move-file hidden>
      </div>
      <p class="muted" data-move-result hidden></p>
    </div>`;
}

const ADDED = [
  ['feeds', 'feed'], ['folders', 'folder'], ['articles', 'article'], ['items', 'stash item'],
  ['stash_folders', 'stash folder'], ['smart_lists', 'smart list'], ['stash_rules', 'rule'], ['muted_words', 'muted word'],
];

async function bringIn(section, file) {
  const result = $('[data-move-result]', section);
  const button = $('[data-move=choose]', section);
  button.disabled = true;
  result.hidden = false;
  result.textContent = `Bringing in ${file.name}…`;
  try {
    const form = new FormData();
    form.append('file', file);
    const counts = await api('POST', '/api/account/import', form);
    const added = ADDED.filter(([key]) => counts[key]).map(([key, word]) => plural(counts[key], word));
    result.innerHTML = `${added.length ? `Added ${esc(added.join(', '))}.` : 'Everything in that file was already here.'}
      ${counts.skipped.length ? `<br>Not brought in: ${counts.skipped.slice(0, 5).map(esc).join('; ')}${counts.skipped.length > 5 ? '…' : ''}` : ''}`;
    toast('Brought in. Reloading…');
    setTimeout(() => location.reload(), 1500);
  } catch (err) {
    result.textContent = err.message;
    button.disabled = false;
  }
}

export function wireMove(root) {
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-move=choose]');
    if (button) $('[data-move-file]', button.closest('[data-move-section]')).click();
  });
  root.addEventListener('change', (e) => {
    const input = e.target.closest('[data-move-file]');
    if (!input?.files?.[0]) return;
    bringIn(input.closest('[data-move-section]'), input.files[0]);
    input.value = '';
  });
}
