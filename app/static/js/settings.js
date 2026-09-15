/* Settings: your account, everyone's accounts (admins), and API tokens for the extension, email worker and apps. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { els } from './state.js';
import { $, agoLong, esc, fullDate } from './util.js';

const timestamp = (iso) => Math.floor(Date.parse(iso) / 1000);
const SIGN_IN_LABELS = { password: 'Password', google: 'Google', oidc: 'Single sign-on', dev: 'Local dev login' };
const PASSWORD_LABEL = (hint) => `<span>New password <small>(${hint})</small></span>`;

let me = null;

export function showSettings() {
  const origin = location.origin;
  els.settings.innerHTML = `
    <h3>Your account</h3>
    <div data-account><p class="muted">Loading…</p></div>

    <div data-accounts-section hidden>
      <h3>Accounts</h3>
      <div class="org-head">
        <p class="muted">Everyone who can sign in. Accounts you add here sign in with a password. People who use
          Google or single sign-on show up after their first sign-in.</p>
        <div class="org-actions">
          <button class="btn btn-sm btn-primary" data-settings="new-account">${icon('plus')}Add account</button>
        </div>
      </div>
      <div data-account-list><p class="muted">Loading…</p></div>
    </div>

    <h3>Connected apps</h3>
    <div class="org-head">
      <p class="muted">The browser extension, email worker and phone apps sign in with an API token. Create one for
        each so you can revoke it on its own. A token is shown only once, right after you create it.</p>
      <div class="org-actions">
        <button class="btn btn-sm btn-primary" data-settings="new-token">${icon('plus')}New token</button>
      </div>
    </div>
    <div data-token-list><p class="muted">Loading…</p></div>

    <h3>Setting up a client</h3>
    <div class="setup">
      <p>Server URL: <code>${esc(origin)}</code>
        <button type="button" class="btn btn-sm" data-copy="${esc(origin)}">${icon('copy')}Copy</button></p>
      <ul>
        <li><b>Browser extension</b>: load <code>clients/extension</code> unpacked in Chrome, Edge or Brave, open its
          options, and enter the server URL and a token.</li>
        <li><b>Email</b>: deploy <code>clients/email-worker</code> to Cloudflare with <code>FEEDSTASH_API_BASE</code> set to
          the server URL and <code>FEEDSTASH_API_TOKEN</code> to a token. Hashtags in the subject become tags.</li>
        <li><b>Android and iOS</b>: enter the server URL and a token on the FeedStash app's Settings tab. Sharing to
          FeedStash saves links, text and images.</li>
      </ul>
    </div>`;
  loadAccount();
  loadTokens();
}

/* ---- your account */

async function loadAccount() {
  const box = $('[data-account]', els.settings);
  try {
    me = await api('GET', '/api/me');
  } catch (err) {
    if (box) box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  if (!box?.isConnected) return;
  box.innerHTML = `
    <div class="org-head">
      <p>Signed in as <b>${esc(me.name || me.email)}</b>${me.name ? ` <span class="muted">${esc(me.email)}</span>` : ''}
        ${me.is_admin ? '<span class="muted">· admin</span>' : ''}</p>
      <div class="org-actions">
        ${me.has_password ? `<button class="btn btn-sm" data-settings="change-password">${icon('key')}Change password</button>` : ''}
      </div>
    </div>`;
  if (me.is_admin) {
    $('[data-accounts-section]', els.settings).hidden = false;
    loadAccounts();
  }
}

async function changePassword() {
  const ok = await modal({
    title: 'Change your password',
    confirmText: 'Change password',
    html: `<label>Current password<input type="password" name="current" autocomplete="current-password"></label>
      <label>${PASSWORD_LABEL('at least 8 characters')}<input type="password" name="next" autocomplete="new-password"></label>`,
    onSubmit: (fd) => api('POST', '/api/account/password', {
      current_password: fd.get('current') || '',
      new_password: fd.get('next') || '',
    }),
  });
  if (ok) toast('Password changed');
}

/* ---- accounts (admins) */

async function loadAccounts() {
  const box = $('[data-account-list]', els.settings);
  if (!box) return;
  try {
    const accounts = await api('GET', '/api/accounts');
    box.innerHTML = `<div class="table-wrap"><table class="org-table">
      <thead><tr><th>Account</th><th>Signs in with</th><th>Role</th><th>Added</th><th></th></tr></thead>
      <tbody>${accounts.map((account) => `<tr>
        <td>${esc(account.name || account.email)}${account.name ? `<div class="muted">${esc(account.email)}</div>` : ''}</td>
        <td>${esc(SIGN_IN_LABELS[account.sign_in] || account.sign_in)}${account.has_password && account.sign_in !== 'password' ? ' and a password' : ''}</td>
        <td>${account.is_admin ? 'Admin' : 'Member'}</td>
        <td>${esc(fullDate(account.created_at))}</td>
        <td class="row-actions">${account.id === me?.id ? '<span class="muted">You</span>' : `
          <button class="btn btn-sm" data-settings="set-password" data-id="${account.id}" data-name="${esc(account.email)}">Set password</button>
          <button class="btn btn-sm" data-settings="toggle-admin" data-id="${account.id}" data-admin="${account.is_admin}" data-name="${esc(account.email)}">${account.is_admin ? 'Remove admin' : 'Make admin'}</button>
          <button class="btn btn-sm" data-settings="remove-account" data-id="${account.id}" data-name="${esc(account.email)}">Remove</button>`}</td>
      </tr>`).join('')}</tbody></table></div>`;
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

async function newAccount() {
  const created = await modal({
    title: 'Add an account',
    confirmText: 'Add account',
    html: `<label>Name<input type="text" name="name" maxlength="100" autocomplete="off"></label>
      <label>Email<input type="email" name="email" autocomplete="off"></label>
      <label>${PASSWORD_LABEL('at least 8 characters; they can change it later')}<input type="password" name="password" autocomplete="new-password"></label>
      <label class="check"><input type="checkbox" name="admin"> Admin (can manage accounts)</label>`,
    onSubmit: (fd) => api('POST', '/api/accounts', {
      name: (fd.get('name') || '').trim() || null,
      email: fd.get('email') || '',
      password: fd.get('password') || '',
      is_admin: fd.get('admin') === 'on',
    }),
  });
  if (!created || created === true) return;
  loadAccounts();
  toast(`Added ${created.email}`);
}

async function setPassword(id, name) {
  const ok = await modal({
    title: `Set a password for ${name}`,
    confirmText: 'Set password',
    html: `<p class="muted">They can sign in with it right away, and change it in Settings.</p>
      <label>${PASSWORD_LABEL('at least 8 characters')}<input type="password" name="password" autocomplete="new-password"></label>`,
    onSubmit: (fd) => api('PATCH', `/api/accounts/${id}`, { password: fd.get('password') || '' }),
  });
  if (!ok) return;
  loadAccounts();
  toast(`Password set for ${name}`);
}

async function toggleAdmin(id, isAdmin, name) {
  try {
    await api('PATCH', `/api/accounts/${id}`, { is_admin: !isAdmin });
    loadAccounts();
    toast(isAdmin ? `${name} is no longer an admin` : `${name} is now an admin`);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

async function removeAccount(id, name) {
  const ok = await modal({
    title: `Remove ${name}?`,
    confirmText: 'Remove',
    danger: true,
    html: '<p>Their feeds, stash, screenshots and API tokens are deleted too. This can’t be undone.</p>',
    onSubmit: () => api('DELETE', `/api/accounts/${id}`),
  });
  if (!ok) return;
  loadAccounts();
  toast(`Removed ${name}`);
}

/* ---- API tokens */

async function loadTokens() {
  const box = $('[data-token-list]', els.settings);
  if (!box) return;
  try {
    const tokens = await api('GET', '/api/tokens');
    box.innerHTML = tokens.length
      ? `<div class="table-wrap"><table class="org-table">
          <thead><tr><th>App</th><th>Token</th><th>Created</th><th>Last used</th><th></th></tr></thead>
          <tbody>${tokens.map((token) => `<tr>
            <td><span class="token-app">${icon('key')}${esc(token.clientName)}</span></td>
            <td><code>${esc(token.tokenPreview)}</code></td>
            <td>${esc(fullDate(timestamp(token.createdAt)))}</td>
            <td>${token.lastUsedAt ? esc(agoLong(timestamp(token.lastUsedAt))) : '<span class="muted">Never</span>'}</td>
            <td class="row-actions"><button class="btn btn-sm" data-settings="revoke" data-id="${token.id}" data-name="${esc(token.clientName)}">Revoke</button></td>
          </tr>`).join('')}</tbody></table></div>`
      : '<p class="muted">No tokens yet.</p>';
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

async function copyFrom(button) {
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Select and copy it manually';
  }
}

async function newToken() {
  const created = await modal({
    title: 'New API token',
    confirmText: 'Create',
    html: `<label>App name<input type="text" name="name" maxlength="100" placeholder="Chrome extension, Pixel phone, email…" autocomplete="off"></label>`,
    onSubmit: async (fd) => {
      const name = (fd.get('name') || '').trim();
      if (!name) throw new Error('Give the token a name');
      return api('POST', '/api/tokens', { clientName: name });
    },
  });
  if (!created || created === true) return;
  loadTokens();
  await modal({
    title: 'Copy your token',
    confirmText: 'Done',
    html: `<p>Enter this token in <b>${esc(created.clientName)}</b>. It won't be shown again.</p>
      <label>Token<input type="text" readonly value="${esc(created.token)}" data-token-value></label>
      <p><button type="button" class="btn btn-sm" data-copy="${esc(created.token)}">${icon('copy')}Copy token</button></p>`,
    onOpen: (dialog) => dialog.addEventListener('click', (e) => {
      const button = e.target.closest('[data-copy]');
      if (button) copyFrom(button);
    }),
  });
}

async function revoke(id, name) {
  const ok = await modal({
    title: `Revoke “${name}”?`,
    confirmText: 'Revoke',
    danger: true,
    html: '<p>Apps using this token stop working until you give them a new one.</p>',
    onSubmit: () => api('DELETE', `/api/tokens/${id}`),
  });
  if (!ok) return;
  loadTokens();
  toast(`Revoked ${name}`);
}

export function wireSettings() {
  els.settings.addEventListener('click', (e) => {
    const copy = e.target.closest('[data-copy]');
    if (copy) return copyFrom(copy);
    const button = e.target.closest('[data-settings]');
    if (!button) return;
    const { id, name } = button.dataset;
    switch (button.dataset.settings) {
      case 'new-token': newToken(); break;
      case 'revoke': revoke(Number(id), name); break;
      case 'change-password': changePassword(); break;
      case 'new-account': newAccount(); break;
      case 'set-password': setPassword(Number(id), name); break;
      case 'toggle-admin': toggleAdmin(Number(id), button.dataset.admin === 'true', name); break;
      case 'remove-account': removeAccount(Number(id), name); break;
    }
  });
}
