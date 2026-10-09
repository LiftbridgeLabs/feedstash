/* The keyboard shortcuts, listed once: the sheet that ? opens (and Settings links to) is built from this, so it
   can't drift from keyboard.js. */

import { esc } from './util.js';

export const SHORTCUTS = [
  ['Anywhere', [
    [['c'], 'Save something to your stash'],
    [['/'], 'Search'],
    [['?'], 'Show these shortcuts'],
    [['Esc'], 'Close the open article, item or menu'],
  ]],
  ['In a list of articles', [
    [['j', 'k'], 'Open the next / previous article'],
    [['n', 'p'], 'Select the next / previous article without opening it'],
    [['o', 'Enter'], 'Open or close the selected article'],
    [['v'], 'Open the original page in a new tab'],
    [['m'], 'Mark read or unread'],
    [['s'], 'Read later'],
    [['b'], 'Save to stash'],
    [['r'], 'Refresh'],
    [['Shift', 'A'], 'Mark everything in the list read'],
  ]],
];

const keys = (list) => list.map((key) => `<kbd>${esc(key)}</kbd>`).join(list[0] === 'Shift' ? ' + ' : ' ');

let open = null;

/** Shows the shortcuts sheet (pressing ? again, Esc or Close closes it). */
export function showShortcuts() {
  if (open) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'modal shortcuts';
  dialog.innerHTML = `
    <form method="dialog">
      <h2>Keyboard shortcuts</h2>
      ${SHORTCUTS.map(([group, rows]) => `
        <h3>${esc(group)}</h3>
        <dl>${rows.map(([combo, what]) => `<div><dt>${keys(combo)}</dt><dd>${esc(what)}</dd></div>`).join('')}</dl>`).join('')}
      <p class="muted">Shortcuts don't work while you're typing in a box.</p>
      <div class="modal-actions"><button class="btn btn-primary" autofocus>Close</button></div>
    </form>`;
  dialog.addEventListener('keydown', (e) => {
    if (e.key === '?') dialog.close();
  });
  dialog.addEventListener('close', () => {
    dialog.remove();
    open = null;
  });
  document.body.append(dialog);
  open = dialog;
  dialog.showModal();
}
