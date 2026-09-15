/* Drag the sidebar's edge to make it narrower or wider; the width is remembered in this browser. */

import { loadJSON, saveJSON } from './util.js';

const DEFAULT = 272;
const MIN = 200;
const MAX = 360;
const KEY = 'reader.sidebarWidth';

function apply(width) {
  document.documentElement.style.setProperty('--sidebar-w', `${width}px`);
}

export function wireSidebarWidth() {
  const handle = document.getElementById('sidebar-resize');
  const saved = Number(loadJSON(KEY, DEFAULT));
  apply(Number.isFinite(saved) ? Math.min(MAX, Math.max(MIN, saved)) : DEFAULT);

  let dragging = false;
  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    try {
      handle.setPointerCapture(e.pointerId); // keeps the drag alive when the mouse outruns the 8px handle
    } catch {
      /* not a real pointer (synthetic event): the moves still arrive on the handle */
    }
    document.body.classList.add('resizing');
    e.preventDefault();
  });
  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const width = Math.round(Math.min(MAX, Math.max(MIN, e.clientX)));
    apply(width);
    saveJSON(KEY, width);
  });
  const stop = () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('resizing');
  };
  handle.addEventListener('pointerup', stop);
  handle.addEventListener('pointercancel', stop);
  handle.addEventListener('dblclick', () => {
    apply(DEFAULT);
    saveJSON(KEY, DEFAULT);
  });
}
