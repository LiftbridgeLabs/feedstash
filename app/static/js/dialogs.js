/* Modal dialogs (native <dialog>) and toast notifications. */

import { els } from './state.js';
import { $, esc } from './util.js';

/**
 * Shows a form dialog. Resolves with onSubmit's result (or true), or null when cancelled.
 * If onSubmit throws, its message is shown in the dialog and the dialog stays open.
 */
export function modal({ title, html, confirmText = 'Save', busyText, danger = false, onOpen, onSubmit }) {
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'modal';
    dialog.innerHTML = `
      <form novalidate>
        <h2>${esc(title)}</h2>
        <div class="modal-body">${html}</div>
        <p class="modal-error" hidden></p>
        <div class="modal-actions">
          <button type="button" class="btn" data-cancel>Cancel</button>
          <button type="submit" class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${esc(confirmText)}</button>
        </div>
      </form>`;
    document.body.append(dialog);
    const form = $('form', dialog);
    const error = $('.modal-error', dialog);
    const submit = $('[type=submit]', dialog);
    let result = null;

    dialog.addEventListener('close', () => {
      dialog.remove();
      resolve(result);
    });
    $('[data-cancel]', dialog).addEventListener('click', () => dialog.close());
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (submit.disabled) return;
      error.hidden = true;
      submit.disabled = true;
      if (busyText) submit.textContent = busyText;
      try {
        const fd = new FormData(form);
        const value = onSubmit ? await onSubmit(fd) : fd;
        result = value === undefined || value === null ? true : value;
        dialog.close();
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        submit.disabled = false;
        submit.textContent = confirmText;
      }
    });

    onOpen?.(dialog);
    dialog.showModal();
    const first = $('input:not([type=checkbox]), select', dialog);
    if (first) {
      first.focus();
      first.select?.();
    }
  });
}

/** Asks for one line of text. Resolves with the trimmed value, or null when cancelled. */
export async function promptDialog({ title, label, value = '', confirmText = 'Save', onSubmit }) {
  let saved = null;
  const ok = await modal({
    title,
    confirmText,
    html: `<label>${esc(label)}<input type="text" name="value" value="${esc(value)}" maxlength="200" autocomplete="off"></label>`,
    onSubmit: async (fd) => {
      const v = (fd.get('value') || '').trim();
      if (!v) throw new Error(`${label} can't be empty`);
      if (v !== value && onSubmit) await onSubmit(v);
      saved = v;
    },
  });
  return ok ? saved : null;
}

let toastTimer = null;
export function toast(message, { action, onAction, error = false, duration = 4000 } = {}) {
  const t = els.toast;
  t.className = `toast${error ? ' error' : ''}`;
  t.innerHTML = `<span>${esc(message)}</span>${action ? `<button type="button">${esc(action)}</button>` : ''}`;
  t.hidden = false;
  if (action) {
    $('button', t).addEventListener('click', async () => {
      t.hidden = true;
      try {
        await onAction();
      } catch (err) {
        toast(err.message, { error: true });
      }
    });
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, action ? 8000 : duration);
}
