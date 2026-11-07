/* Settings → You → Two-step sign-in: a code from an authenticator app after the password, recovery codes for a lost
   phone, and turning it off. Only for accounts with a password (Google and single sign-on have their own). */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { $, copyText, esc } from './util.js';

const PASSWORD_FIELD = `<label>Your password<input type="password" name="password" autocomplete="current-password"></label>`;

export function twoStepSectionHTML() {
  return `
    <div data-two-step-section hidden>
      <h3>Two-step sign-in</h3>
      <p class="muted">After your password, signing in asks for a code from an authenticator app on your phone
        (1Password, Google Authenticator, the iPhone's Passwords app). Someone who learns your password still can't
        get in. Google and single sign-on use their own, and the phone app, extension and reader apps are unaffected.</p>
      <div data-two-step><p class="muted">Loading…</p></div>
    </div>`;
}

export async function loadTwoStep(root, me) {
  const section = $('[data-two-step-section]', root);
  if (!section) return;
  section.hidden = !me.has_password;
  if (!me.has_password) return;
  const box = $('[data-two-step]', section);
  let s;
  try {
    s = await api('GET', '/api/account/two-step');
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  box.innerHTML = s.enabled ? `
      <p data-two-step-state><b>On.</b> ${s.recovery_codes_left} of 10 recovery codes left.</p>
      ${s.recovery_codes_left <= 3 ? '<p class="muted">Running low: make new ones so you can still get in without your phone.</p>' : ''}
      <div class="org-actions">
        <button class="btn btn-sm" data-two-step-action="codes">${icon('key')}New recovery codes</button>
        <button class="btn btn-sm" data-two-step-action="off">Turn off</button>
      </div>`
    : `<p data-two-step-state>Off.</p>
      <div class="org-actions"><button class="btn btn-sm btn-primary" data-two-step-action="on">Turn on</button></div>`;
}

function codesHTML(codes) {
  return `<p>Keep these somewhere safe, like your password manager. Each works once, instead of a code from your
      phone. They're shown only this once.</p>
    <ol class="recovery-codes" data-recovery-codes>${codes.map((code) => `<li><code>${esc(code)}</code></li>`).join('')}</ol>
    <p class="org-actions">
      <button type="button" class="btn btn-sm" data-copy-codes>${icon('copy')}Copy</button>
      <a class="btn btn-sm" data-download-codes download="feedstash-recovery-codes.txt">Download</a>
    </p>`;
}

async function showCodes(codes) {
  const text = `FeedStash recovery codes for ${location.host}\nEach works once.\n\n${codes.join('\n')}\n`;
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  await modal({
    title: 'Your recovery codes',
    confirmText: "I've saved them",
    html: codesHTML(codes),
    onOpen: (dialog) => {
      $('[data-download-codes]', dialog).href = url;
      $('[data-copy-codes]', dialog).addEventListener('click', async (e) => {
        e.currentTarget.textContent = await copyText(text, e.currentTarget.parentElement) ? 'Copied' : 'Select and copy them';
      });
    },
  });
  URL.revokeObjectURL(url);
}

async function turnOn(root, me) {
  // First the password again, then the QR code and a first code from the app.
  const setup = await modal({
    title: 'Turn on two-step sign-in',
    confirmText: 'Next',
    html: `<p>First, your password again.</p>${PASSWORD_FIELD}`,
    onSubmit: (fd) => api('POST', '/api/account/two-step/start', { password: fd.get('password') || '' }),
  });
  if (!setup) return;
  const codes = await modal({
    title: 'Scan with your authenticator app',
    confirmText: 'Turn on',
    // The QR code is SVG the server drew from the otpauth:// link; nothing anyone typed is in it.
    html: `<p>Scan this with your authenticator app, then type the 6-digit code it shows for FeedStash.</p>
      <div class="qr-code">${setup.svg}</div>
      <details class="connect-manual"><summary>Can't scan it?</summary>
        <label>Setup key<input type="text" readonly value="${esc(setup.secret)}"></label>
      </details>
      <label>Code from the app<input type="text" name="code" autocomplete="one-time-code" inputmode="numeric" maxlength="12"></label>`,
    onSubmit: async (fd) => (await api('POST', '/api/account/two-step/confirm', { code: fd.get('code') || '' })).recovery_codes,
  });
  if (!codes) return;
  await showCodes(codes);
  toast('Two-step sign-in is on. Other browsers were signed out.');
  loadTwoStep(root, me);
}

async function newCodes(root, me) {
  const codes = await modal({
    title: 'New recovery codes',
    confirmText: 'Make new codes',
    html: `<p>Your old recovery codes stop working.</p>${PASSWORD_FIELD}`,
    onSubmit: async (fd) => (await api('POST', '/api/account/two-step/recovery-codes', { password: fd.get('password') || '' })).recovery_codes,
  });
  if (!codes) return;
  await showCodes(codes);
  loadTwoStep(root, me);
}

async function turnOff(root, me) {
  const done = await modal({
    title: 'Turn off two-step sign-in',
    confirmText: 'Turn off',
    danger: true,
    html: `<p>Signing in will ask for your password only. Your recovery codes stop working.</p>${PASSWORD_FIELD}`,
    onSubmit: (fd) => api('POST', '/api/account/two-step/off', { password: fd.get('password') || '' }),
  });
  if (!done) return;
  toast('Two-step sign-in is off');
  loadTwoStep(root, me);
}

/** Wires the section's buttons; `currentUser` returns who's signed in (loaded with the rest of Settings). */
export function wireTwoStep(root, currentUser) {
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-two-step-action]');
    if (!button) return;
    const me = currentUser();
    const run = { on: turnOn, codes: newCodes, off: turnOff }[button.dataset.twoStepAction];
    run?.(root, me).catch((err) => toast(err.message, { error: true }));
  });
}
