/* Settings → Email: the mailbox FeedStash checks for you. Forward anything there and it lands in your stash. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { els } from './state.js';
import { $, $$, agoLong, esc } from './util.js';

const timestamp = (iso) => Math.floor(Date.parse(iso) / 1000);

/* Providers people actually use. Proton has no IMAP (it needs Bridge, a paid desktop app) and Outlook.com
   requires OAuth, so neither can be connected this way. */
const PROVIDERS = [
  ['gmail', 'Gmail', 'imap.gmail.com', 993, 'Needs an app password: Google Account → Security → 2-Step Verification → App passwords.'],
  ['icloud', 'iCloud', 'imap.mail.me.com', 993, 'Needs an app-specific password: account.apple.com → Sign-In and Security.'],
  ['fastmail', 'Fastmail', 'imap.fastmail.com', 993, 'Needs an app password: Settings → Privacy & Security → Integrations.'],
  ['yahoo', 'Yahoo', 'imap.mail.yahoo.com', 993, 'Needs an app password: Account Security → Generate app password.'],
  ['zoho', 'Zoho Mail', 'imap.zoho.com', 993, 'Needs an app password: My Account → Security → App passwords.'],
  ['other', 'Something else', '', 993, 'Enter the IMAP server your provider lists. Most want an app password rather than your normal one.'],
];

let mail = null;

export function mailSectionHTML() {
  return `
    <h3>Email to your stash</h3>
    <div class="org-head">
      <p class="muted">Forward an email to a mailbox and FeedStash saves it: subject as the title, #hashtags as
        tags, $Folder to file it (made if it's new), and any links saved with a preview. FeedStash reaches out to
        the mailbox, so this works even with no ports open. A mailbox kept just for this is tidiest.</p>
    </div>
    <div data-mail><p class="muted">Loading…</p></div>`;
}

export async function loadMail(root) {
  const box = $('[data-mail]', root);
  if (!box) return;
  try {
    mail = await api('GET', '/api/mail');
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  if (!box.isConnected) return;
  box.innerHTML = mail.connected ? connectedHTML() : formHTML();
}

function statusLine() {
  if (!mail.connected) return '';
  if (mail.lastError) return `<span class="status-err">${esc(mail.lastError)}</span>`;
  if (!mail.lastCheckedAt) return '<span class="muted">Not checked yet.</span>';
  return `<span class="muted">Checked ${esc(agoLong(timestamp(mail.lastCheckedAt)))} ·
    ${mail.savedCount} saved so far · checking every ${mail.pollMinutes} minutes.</span>`;
}

function connectedHTML() {
  return `
    <div class="setting-row">
      <span><b>${esc(mail.username)}</b> <span class="muted">on ${esc(mail.host)}</span></span>
      <div class="org-actions">
        <button class="btn btn-sm" data-mail-action="check">${icon('refresh')}Check now</button>
        <button class="btn btn-sm" data-mail-action="edit">${icon('sliders')}Change</button>
        <button class="btn btn-sm" data-mail-action="disconnect">Disconnect</button>
      </div>
      <p class="muted">${statusLine()}</p>
    </div>`;
}

function providerOptions(selected) {
  return PROVIDERS
    .map(([id, label]) => `<option value="${id}" ${id === selected ? 'selected' : ''}>${label}</option>`)
    .join('');
}

function formHTML() {
  const [, , , , firstHint] = PROVIDERS[0];
  return `
    <form class="mail-form" data-mail-form>
      <label>Provider<select name="provider">${providerOptions('gmail')}</select></label>
      <p class="muted" data-provider-hint>${esc(firstHint)}</p>
      <label>Email address<input type="email" name="username" value="${esc(mail.username || '')}" autocomplete="off"
        data-1p-ignore data-lpignore="true" data-form-type="other" placeholder="stash@gmail.com"></label>
      <label>App password<input type="password" name="password" autocomplete="off"
        placeholder="${mail.connected ? 'Leave empty to keep the saved one' : ''}"></label>
      <details data-advanced>
        <summary>Server details</summary>
        <label>IMAP server<input type="text" name="host" value="${esc(mail.host || 'imap.gmail.com')}" autocomplete="off"></label>
        <label>Port<input type="number" name="port" value="${mail.port || 993}" min="1" max="65535"></label>
        <label>Folder<input type="text" name="folder" value="${esc(mail.folder || 'INBOX')}" autocomplete="off"></label>
        <label>Only save mail from <small>(optional; addresses or @domains, comma separated)</small>
          <input type="text" name="allowedSenders" value="${esc((mail.allowedSenders || []).join(', '))}" autocomplete="off"></label>
      </details>
      <div class="org-actions">
        <button type="submit" class="btn btn-sm btn-primary">${icon('check')}Connect mailbox</button>
        ${mail.connected ? '<button type="button" class="btn btn-sm" data-mail-action="cancel">Cancel</button>' : ''}
      </div>
      <p class="muted" data-mail-message></p>
    </form>`;
}

function applyProvider(form) {
  const id = $('select[name=provider]', form).value;
  const [, , host, port, hint] = PROVIDERS.find(([value]) => value === id) || PROVIDERS.at(-1);
  $('[data-provider-hint]', form).textContent = hint;
  if (host) $('input[name=host]', form).value = host;
  $('input[name=port]', form).value = port;
  if (!host) $('[data-advanced]', form).open = true;
}

async function connect(form) {
  const data = new FormData(form);
  const message = $('[data-mail-message]', form);
  const button = $('[type=submit]', form);
  button.disabled = true;
  message.textContent = 'Connecting…';
  try {
    mail = await api('PUT', '/api/mail', {
      host: (data.get('host') || '').trim(),
      port: Number(data.get('port')) || 993,
      username: (data.get('username') || '').trim(),
      password: data.get('password') || '',
      folder: (data.get('folder') || 'INBOX').trim(),
      allowedSenders: (data.get('allowedSenders') || '').split(',').map((s) => s.trim()).filter(Boolean),
      enabled: true,
    });
    const check = await api('POST', '/api/mail/test');
    if (!check.ok) {
      message.innerHTML = `<span class="status-err">${esc(check.error)}</span>`;
      button.disabled = false;
      return;
    }
    await loadMail(els.settings);
    toast('Mailbox connected. Forward something to it and it lands in your stash.');
  } catch (err) {
    message.innerHTML = `<span class="status-err">${esc(err.message)}</span>`;
    button.disabled = false;
  }
}

async function checkNow(button) {
  button.disabled = true;
  try {
    const result = await api('POST', '/api/mail/check');
    if (result.error) toast(result.error, { error: true });
    else toast(result.saved ? `Saved ${result.saved} message${result.saved === 1 ? '' : 's'}` : 'Nothing new in the mailbox');
    await loadMail(els.settings);
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    button.disabled = false;
  }
}

async function disconnect() {
  const ok = await modal({
    title: 'Disconnect this mailbox?',
    confirmText: 'Disconnect',
    danger: true,
    html: '<p>FeedStash stops checking it and forgets the password. What it already saved stays in your stash.</p>',
    onSubmit: () => api('DELETE', '/api/mail'),
  });
  if (!ok) return;
  await loadMail(els.settings);
  toast('Mailbox disconnected');
}

export function wireMail(root) {
  root.addEventListener('submit', (e) => {
    if (!e.target.matches('[data-mail-form]')) return;
    e.preventDefault();
    connect(e.target);
  });
  root.addEventListener('change', (e) => {
    if (e.target.matches('[data-mail-form] select[name=provider]')) applyProvider(e.target.closest('form'));
  });
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-mail-action]');
    if (!button) return;
    switch (button.dataset.mailAction) {
      case 'check': checkNow(button); break;
      case 'edit': $('[data-mail]', root).innerHTML = formHTML(); break;
      case 'cancel': $('[data-mail]', root).innerHTML = connectedHTML(); break;
      case 'disconnect': disconnect(); break;
    }
  });
}
