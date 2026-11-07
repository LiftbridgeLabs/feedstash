/* Settings → You → Passkeys: sign in with Face ID, Touch ID, Windows Hello or a phone instead of a password. Adding
   one asks for the password again (accounts that have one); renaming and removing don't. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { $, agoLong, esc, fullDate } from './util.js';
import { creationOptions, credentialJSON, passkeyErrorMessage, passkeysSupported } from './webauthn.js';

export function passkeysSectionHTML() {
  return `
    <h3>Passkeys</h3>
    <p class="muted">Sign in with Face ID, Touch ID, Windows Hello or your phone instead of typing your password. A
      passkey counts as both steps of two-step sign-in. The phone app, extension and reader apps are unaffected.</p>
    <div data-passkeys><p class="muted">Loading…</p></div>`;
}

/** A starting name for a new passkey: where it's being made. */
function deviceName() {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return 'iPhone';
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'iPad';
  if (/Android/.test(ua)) return 'Android';
  if (/Macintosh/.test(ua)) return 'Mac';
  if (/Windows/.test(ua)) return 'Windows';
  return 'Passkey';
}

export async function loadPasskeys(root) {
  const box = $('[data-passkeys]', root);
  if (!box) return;
  let s;
  try {
    s = await api('GET', '/api/account/passkeys');
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  box.dataset.hasPassword = s.has_password ? 'true' : '';
  const list = s.passkeys.length
    ? `<div class="table-wrap"><table class="org-table" data-passkey-list>
        <thead><tr><th>Passkey</th><th>Added</th><th>Last used</th><th></th></tr></thead>
        <tbody>${s.passkeys.map((p) => `<tr>
          <td><span class="token-app">${icon('key')}${esc(p.name)}</span></td>
          <td>${esc(fullDate(p.created_at))}</td>
          <td>${p.last_used_at ? esc(agoLong(p.last_used_at)) : '<span class="muted">Never</span>'}</td>
          <td class="row-actions"><button class="btn btn-sm" data-passkey-action="rename" data-id="${p.id}" data-name="${esc(p.name)}">Rename</button>
            <button class="btn btn-sm" data-passkey-action="remove" data-id="${p.id}" data-name="${esc(p.name)}">Remove</button></td>
        </tr>`).join('')}</tbody></table></div>`
    : '';
  let add = '<div class="org-actions"><button class="btn btn-sm btn-primary" data-passkey-action="add">Add a passkey</button></div>';
  if (!s.available) add = `<p class="muted" data-passkey-unavailable>${esc(s.reason)}</p>`;
  else if (!passkeysSupported()) add = '<p class="muted" data-passkey-unavailable>This browser can\'t make passkeys.</p>';
  box.innerHTML = list + add;
}

async function addPasskey(root) {
  const hasPassword = Boolean($('[data-passkeys]', root)?.dataset.hasPassword);
  // The options are fetched as the dialog opens, so pressing Next goes straight to the device (Safari wants the
  // passkey step to follow the click directly).
  let ready = null;
  const added = await modal({
    title: 'Add a passkey',
    confirmText: 'Next',
    html: `<p>Your device or password manager makes the passkey and keeps it. Next, it asks for your face,
        fingerprint or PIN.</p>
      <label>Name it<input type="text" name="name" maxlength="60" value="${esc(deviceName())}"></label>
      ${hasPassword ? '<label>Your password<input type="password" name="password" autocomplete="current-password"></label>' : ''}`,
    onOpen: () => { ready = api('POST', '/api/account/passkeys/options'); ready.catch(() => {}); },
    onSubmit: async (fd) => {
      const { options } = await ready;
      let credential;
      try {
        credential = await navigator.credentials.create({ publicKey: creationOptions(options) });
      } catch (err) {
        ready = api('POST', '/api/account/passkeys/options');  // a fresh challenge for another try
        ready.catch(() => {});
        throw new Error(passkeyErrorMessage(err) || 'No passkey was made. Press Next to try again.');
      }
      try {
        return await api('POST', '/api/account/passkeys', {
          name: fd.get('name') || '', password: fd.get('password') || '', credential: credentialJSON(credential),
        });
      } catch (err) {
        ready = api('POST', '/api/account/passkeys/options');
        ready.catch(() => {});
        throw err;
      }
    },
  });
  if (!added) return;
  toast(`Passkey “${added.name}” added. Use it on the sign-in page.`);
  loadPasskeys(root);
}

async function renamePasskey(root, id, name) {
  const done = await modal({
    title: 'Rename passkey',
    html: `<label>Name<input type="text" name="name" maxlength="60" value="${esc(name)}"></label>`,
    onSubmit: (fd) => api('PATCH', `/api/account/passkeys/${id}`, { name: fd.get('name') || '' }),
  });
  if (done) loadPasskeys(root);
}

async function removePasskey(root, id, name) {
  const done = await modal({
    title: `Remove “${name}”?`,
    confirmText: 'Remove',
    danger: true,
    html: `<p>It won't sign you in here any more. Your device may still list it: delete it there too, in its
      passwords or passkeys settings.</p>`,
    onSubmit: () => api('DELETE', `/api/account/passkeys/${id}`),
  });
  if (!done) return;
  toast('Passkey removed');
  loadPasskeys(root);
}

export function wirePasskeys(root) {
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-passkey-action]');
    if (!button) return;
    const { passkeyAction: action, id, name } = button.dataset;
    const run = { add: () => addPasskey(root), rename: () => renamePasskey(root, id, name), remove: () => removePasskey(root, id, name) }[action];
    run?.().catch((err) => toast(err.message, { error: true }));
  });
}
