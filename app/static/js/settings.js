/* Settings: your account, everyone's accounts (admins), and API tokens for the extension, email worker and apps. */

import { api } from './api.js';
import { modal, promptDialog, toast } from './dialogs.js';
import { icon } from './icons.js';
import { importSectionHTML, renderImportPlan, wireImport } from './importlinks.js';
import { loadMail, mailSectionHTML, wireMail } from './mailbox.js';
import { applySections, setPref } from './menus.js';
import { showShortcuts } from './shortcuts.js';
import { renderNav } from './sidebar.js';
import { loadLogs, logsSectionHTML, wireLogs } from './logsettings.js';
import { loadSignIn, signInSectionHTML, wireSignIn } from './signinsettings.js';
import { loadTagSettings, tagsSectionHTML, wireTagSettings } from './tagsettings.js';
import { loadRules, rulesSectionHTML, wireRules } from './rules.js';
import { els, showsFeeds, showsStash, state } from './state.js';
import { MODES, SCHEMES, setTheme, theme } from './theme.js';
import { $, $$, agoLong, esc, fullDate } from './util.js';

const timestamp = (iso) => Math.floor(Date.parse(iso) / 1000);
const SIGN_IN_LABELS = { password: 'Password', google: 'Google', oidc: 'Single sign-on', dev: 'Local dev login' };
const PASSWORD_LABEL = (hint) => `<span>New password <small>(${hint})</small></span>`;
const READ_RETENTION_CHOICES = [[1, '1 day'], [3, '3 days'], [7, '1 week'], [14, '2 weeks'], [30, '30 days'], [90, '90 days'], [0, 'Never']];

function readRetentionOptions(current) {
  const choices = READ_RETENTION_CHOICES.some(([days]) => days === current)
    ? READ_RETENTION_CHOICES
    : [...READ_RETENTION_CHOICES, [current, `${current} days`]];
  return choices.map(([days, label]) => `<option value="${days}" ${days === current ? 'selected' : ''}>${label}</option>`).join('');
}

const REPO = 'https://github.com/LiftbridgeLabs/feedstash';
const SUPPORT_EMAIL = 'support@liftbridgelabs.app';
const COFFEE = 'https://buymeacoffee.com/liftbridgelabs';
const FIREFOX_STORE = 'https://addons.mozilla.org/firefox/addon/feedstash-capture/';
const CHROME_STORE = 'https://chromewebstore.google.com/detail/feedstash-capture/kedkaohofjncmokoknimfofbnmgomcob';

let me = null;

/* Settings is split into groups, one shown at a time, each with its own address (#/settings/feeds). Every group
   stays in the page while Settings is open, so switching doesn't reload anything or lose what's been typed. */
export const SETTINGS_GROUPS = [['you', 'You'], ['feeds', 'Feeds'], ['stash', 'Stash'], ['apps', 'Apps'], ['admin', 'Admin']];

const card = (html, attrs = '') => `<section class="settings-card" ${attrs}>${html}</section>`;

/** Opens Settings on a group. With `switching` (already in Settings) only the group changes. */
export function showSettings({ switching = false } = {}) {
  const group = SETTINGS_GROUPS.some(([id]) => id === state.route.id) ? state.route.id : 'you';
  if (switching && $('[data-settings-nav]', els.settings)) {
    selectGroup(group);
    return;
  }
  const origin = location.origin;
  els.settings.innerHTML = `
    <div class="settings-layout">
      <nav class="settings-nav" data-settings-nav aria-label="Settings sections">
        ${SETTINGS_GROUPS.map(([id, label]) => `<a href="#/settings/${id}" data-group-link="${id}" ${id === 'admin' ? 'hidden' : ''}>${label}</a>`).join('')}
      </nav>
      <div class="settings-body">

    <div class="settings-group" data-group="you">
    ${card(`<h3>Your account</h3>
      <div data-account><p class="muted">Loading…</p></div>`)}

    ${card(`<h3>Appearance</h3>
    <div class="setting-row">
      <label for="theme-mode">Theme</label>
      <select id="theme-mode" data-settings-field="theme-mode">
        ${MODES.map(([value, label]) => `<option value="${value}" ${value === theme.mode ? 'selected' : ''}>${label}</option>`).join('')}
      </select>
      <p class="muted">Kept in this browser, so each device can look the way you like.</p>
    </div>
    <div class="setting-row">
      <span class="field-label">Colors</span>
      <div class="swatches" data-schemes>${schemeButtons()}</div>
    </div>`)}

    ${card(`<h3>Reading</h3>
    <div class="setting-row">
      <label for="mark-on-scroll">Mark as read while scrolling</label>
      <select id="mark-on-scroll" data-settings-field="mark-on-scroll">
        <option value="off" ${state.prefs.markOnScroll ? '' : 'selected'}>Off</option>
        <option value="on" ${state.prefs.markOnScroll ? 'selected' : ''}>On</option>
      </select>
      <p class="muted">Articles are marked read once they scroll off the top of the list. Kept in this browser; it's
        also in the list's view options.</p>
    </div>
    <div class="setting-row">
      <p class="muted">Move through articles, mark them read and save them without the mouse. Press <kbd>?</kbd>
        anywhere to see the shortcuts.</p>
      <button class="btn btn-sm" data-settings="shortcuts">Keyboard shortcuts</button>
    </div>`, 'data-only="feeds"')}
    </div>

    <div class="settings-group" data-group="feeds" hidden>
    ${card(`<h3>Feeds</h3>
    <div class="org-head">
      <p class="muted">Rename, reorder and move feeds, fix a feed's address, or unfollow.</p>
      <div class="org-actions"><a class="btn btn-sm" href="#/organize">${icon('sliders')}Organize feeds</a></div>
    </div>`, 'data-only="feeds"')}

    ${card(importSectionHTML())}
    </div>

    <div class="settings-group" data-group="stash" hidden>
    ${card(tagsSectionHTML())}
    ${card(mailSectionHTML())}
    ${card(rulesSectionHTML())}
    </div>

    <div class="settings-group" data-group="apps" hidden>
    ${card(`<h3>Connected apps</h3>
    <div class="org-head">
      <p class="muted">Setting up the iPhone or iPad app? <b>Connect a phone or iPad</b> shows a code to scan, so
        there's nothing to type. The extension, email worker and other apps sign in with a token: make one each, so
        you can revoke them separately. A token is shown only once.</p>
      <div class="org-actions">
        <button class="btn btn-sm btn-primary" data-settings="connect-phone">Connect a phone or iPad</button>
        <button class="btn btn-sm" data-settings="new-token">${icon('plus')}New token</button>
      </div>
    </div>
    <div data-token-list><p class="muted">Loading…</p></div>`)}

    ${card(`<h3>Browser extension</h3>
    <p class="muted">Save the page you're on, a link, some text or a screenshot with a right-click or the toolbar
      button. It also sends FeedStash the page as you see it, so sites that turn servers away still get a readable
      copy.</p>
    <div class="org-actions">
      <a class="btn btn-sm btn-primary" href="${CHROME_STORE}" target="_blank" rel="noopener">Get it for Chrome, Edge or Brave</a>
      <a class="btn btn-sm btn-primary" href="${FIREFOX_STORE}" target="_blank" rel="noopener">Get it for Firefox</a>
    </div>
    <p class="steps-title"><b>Chrome, Edge or Brave</b></p>
    <ol class="steps">
      <li>Click <b>Get it for Chrome, Edge or Brave</b>, then the store's add button (<b>Add to Chrome</b>,
        <b>Add to Brave</b> or <b>Get</b> in Edge). In Edge, choose <b>Allow extensions from other stores</b> if it
        asks first.</li>
      <li>Pin the FeedStash icon to the toolbar if you like. It updates itself from the store.</li>
    </ol>
    <p class="muted">Would rather not use the store? <a href="/downloads/feedstash-extension.zip" download>Download it</a>,
      unzip it, open <code>chrome://extensions</code> (<code>edge://extensions</code> in Edge,
      <code>brave://extensions</code> in Brave), turn on <b>Developer mode</b> and choose <b>Load unpacked</b>.</p>
    <p class="steps-title"><b>Firefox</b></p>
    <ol class="steps">
      <li>Click <b>Get it for Firefox</b>, then <b>Add to Firefox</b> on Firefox Add-ons, and <b>Add</b> when Firefox
        asks.</li>
      <li>Pin the FeedStash icon to the toolbar if you like. It updates itself from Firefox Add-ons.</li>
    </ol>
    <p class="steps-title"><b>Then, in any browser</b></p>
    <ol class="steps">
      <li>Click the FeedStash icon → <b>Settings</b>, enter this server's address and a token, and click
        <b>Test connection</b>. If the browser asks to let FeedStash reach your server, choose <b>Allow</b>. Make the
        token under <b>Connected apps</b> above, called something like "extension".</li>
    </ol>
    ${serverAddressHTML(origin)}`)}

    ${card(`<h3>Email with Cloudflare</h3>
    <p class="muted">Send or forward email to an address on your own domain, like <code>stash@yourdomain.com</code>,
      and it lands in your stash within seconds. You need a domain whose email (DNS) is on Cloudflare, a free
      Cloudflare account, and FeedStash reachable from the internet, since Cloudflare delivers the mail to it.
      No domain? Use a mailbox instead: <a href="#/settings/stash">Stash → Email to your stash</a>.</p>
    <div class="org-actions" data-worker-download><a class="btn btn-sm btn-primary" href="/downloads/feedstash-email-worker.js" download>Download the worker script</a></div>
    <ol class="steps">
      <li>Make a token under <b>Connected apps</b> above, called something like "email", and copy it.</li>
      <li>In the Cloudflare dashboard, open <b>Workers &amp; Pages</b> → <b>Create</b> and create a Worker from the
        <b>Hello World</b> starter. Name it <code>feedstash-email-worker</code> and deploy it.</li>
      <li>Click <b>Edit code</b>, delete what's there, paste in the whole worker script you downloaded, and click
        <b>Deploy</b>.</li>
      <li>In the worker's <b>Settings → Variables and Secrets</b>, add:
        <ul>
          <li><code>FEEDSTASH_API_BASE</code>: this server's address as the internet sees it${isLocalAddress(origin) ? '' : ' (below)'}</li>
          <li><code>FEEDSTASH_API_TOKEN</code>: the token, added as a <b>Secret</b></li>
          <li><code>ALLOWED_SENDERS</code>: the addresses you send from, separated by commas. Mail from anyone else
            is turned away, though a determined sender can fake an address.</li>
          <li><code>ADDRESS_SECRET</code> (recommended), also as a <b>Secret</b>: a code only you know, like
            <code>${esc(secretCode())}</code>.
            Mail then has to go to <code>stash+${esc(secretCode())}@yourdomain.com</code>, so knowing your address
            isn't enough to post into your stash.</li>
        </ul></li>
      <li>Open your domain → <b>Email</b> → <b>Email Routing</b> (turn it on if asked), and add a routing rule:
        your address, like <code>stash@yourdomain.com</code>, with the action <b>Send to a Worker</b> →
        <code>feedstash-email-worker</code>. If you set <code>ADDRESS_SECRET</code>, also turn on
        <b>Settings → Subaddressing</b> there.</li>
      <li>Email that address (with <code>+</code> and your code, if you set one) with a subject like
        <code>Test #testing</code>. It shows up in your stash within a few seconds; if it doesn't, the email bounces
        back with the reason.</li>
    </ol>
    ${isLocalAddress(origin)
      ? `<p class="server-address">You're on <code>${esc(origin)}</code>, an address on your own network, which Cloudflare
        can't reach. Use the address you open FeedStash at from outside, like <code>https://feedstash.yourdomain.com</code>.</p>`
      : serverAddressHTML(origin)}`, 'data-only="stash"')}

    ${card(`<h3>Other apps</h3>
    <ul class="steps">
      <li><b>iPhone and iPad</b>: get FeedStash from the App Store, then click <b>Connect a phone or iPad</b> above
        and scan the code. Sharing to FeedStash saves links, text and pictures.</li>
      <li><b>Other reader apps</b> (NetNewsWire, Reeder Classic, lire, Capy Reader): add a <b>FreshRSS</b> or
        <b>Google Reader</b> account with this server's address (some apps want
        <code>${esc(origin)}/api/greader.php</code> instead), your email as the username, and a token as the
        password. They show your feeds; the stash stays here.</li>
    </ul>
    ${serverAddressHTML(origin)}`)}
    </div>

    <div class="settings-group" data-group="admin" hidden>
    ${card(`<div data-accounts-section hidden>
      <h3>Accounts</h3>
      <div class="org-head">
        <p class="muted">Everyone who can sign in. Accounts added here use a password; Google and single sign-on
          accounts appear after their first sign-in.</p>
        <div class="org-actions">
          <button class="btn btn-sm btn-primary" data-settings="new-account">${icon('plus')}Add account</button>
        </div>
      </div>
      <div data-account-list><p class="muted">Loading…</p></div>
    </div>`)}

    ${card(signInSectionHTML())}

    ${card(logsSectionHTML())}

    ${card(`<div data-about-section hidden>
      <h3>About FeedStash</h3>
      <p data-about-version class="muted"></p>
      <div class="org-head">
        <p class="muted">FeedStash is open source. Suggest a feature or report a problem on GitHub, or email
          support.</p>
        <div class="org-actions">
          <a class="btn btn-sm" href="${REPO}/issues/new" target="_blank" rel="noopener">Suggest a feature or report a problem</a>
          <a class="btn btn-sm" href="${REPO}/releases" target="_blank" rel="noopener">Release notes</a>
          <a class="btn btn-sm" href="${REPO}#readme" target="_blank" rel="noopener">Documentation</a>
          <a class="btn btn-sm" data-about-mail href="mailto:${SUPPORT_EMAIL}">${icon('mail')}Email support</a>
          <a class="btn btn-sm" href="${COFFEE}" target="_blank" rel="noopener">Buy me a coffee</a>
        </div>
      </div>
    </div>`)}
    </div>

      </div>
    </div>`;
  applySettingsSections();
  selectGroup(group);
  renderImportPlan(els.settings); // files chosen before leaving Settings are still listed
  loadAccount();
  loadMail(els.settings);
  loadRules(els.settings);
  loadTagSettings(els.settings);
  loadTokens();
  checkWorkerDownload();
}

/** A copy run from source (not the Docker image) has no bundled worker: say where it comes from instead. */
async function checkWorkerDownload() {
  const box = $('[data-worker-download]', els.settings);
  if (!box) return;
  try {
    const response = await fetch('/downloads');
    if (!response.ok) return;
    const available = await response.json();
    if (available.email_worker || !box.isConnected) return;
  } catch {
    return; // offline or the like: leave the button, which explains itself if it fails
  }
  box.innerHTML = `<p class="muted">This copy of FeedStash runs from source, so it doesn't have the ready-made worker
    script (the Docker image builds it). Bundle <code>clients/email-worker</code> with
    <code>npx esbuild src/index.js --bundle --format=esm --minify</code>, or deploy it with wrangler as its README
    describes.</p>`;
}

/** Shows one group and marks it in the menu. A group someone can't use (Admin for others, Stash when they only use
   feeds) falls back to You. */
function selectGroup(group) {
  const link = $(`[data-group-link="${group}"]`, els.settings);
  if (!link || link.hidden) group = 'you';
  $$('[data-group]', els.settings).forEach((el) => { el.hidden = el.dataset.group !== group; });
  $$('[data-group-link]', els.settings).forEach((el) => {
    el.classList.toggle('active', el.dataset.groupLink === group);
    if (el.dataset.groupLink === group) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
  els.content.scrollTop = 0;
}

/** An address only reachable at home: localhost, private ranges, Tailscale's 100.64/10, or a .local name. */
/** A suggested ADDRESS_SECRET for the email worker: ten random letters and digits, the same until the page reloads. */
let suggestedSecret = '';
function secretCode() {
  if (!suggestedSecret) {
    const chars = 'abcdefghjkmnpqrstuvwxyz23456789';  // nothing that reads two ways (l/1, o/0)
    suggestedSecret = [...crypto.getRandomValues(new Uint8Array(10))].map((b) => chars[b % chars.length]).join('');
  }
  return suggestedSecret;
}

function isLocalAddress(origin) {
  let host;
  try {
    host = new URL(origin).hostname.replace(/^\[|\]$/g, '');
  } catch {
    return false;
  }
  if (host === 'localhost' || host.endsWith('.local') || host === '::1') return true;
  if (host.includes(':')) return /^f[cd][0-9a-f]{2}:|^fe[89ab][0-9a-f]:/i.test(host); // IPv6: unique-local, link-local
  const parts = host.split('.').map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n))) return false;
  const [a, b] = parts;
  return a === 127 || a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31)
    || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254);
}

function serverAddressHTML(origin) {
  return `<p class="server-address">This server's address: <code>${esc(origin)}</code>
    <button type="button" class="btn btn-sm" data-copy="${esc(origin)}">${icon('copy')}Copy</button></p>`;
}

/* ---- appearance */

function schemeButtons() {
  return SCHEMES.map(([id, label, color]) => `
    <button type="button" class="swatch ${id === theme.scheme ? 'active' : ''}" data-scheme="${id}">
      <span style="background: ${color}"></span>${esc(label)}
    </button>`).join('');
}

function chooseScheme(scheme) {
  setTheme({ scheme });
  $$('[data-schemes] .swatch', els.settings).forEach((button) => {
    button.classList.toggle('active', button.dataset.scheme === scheme);
  });
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
        <button class="btn btn-sm" data-settings="sign-out-others">${icon('logout')}Sign out other browsers</button>
      </div>
    </div>
    <div class="setting-row">
      <label for="read-retention">Delete read articles after</label>
      <select id="read-retention" data-settings-field="read-retention">${readRetentionOptions(me.read_retention_days)}</select>
      <p class="muted">Counted from when you read them. Articles in Read later are always kept, and everything else
        is still cleared once it's older than this server keeps articles.</p>
    </div>
    <div class="setting-row">
      <label for="sections">Use</label>
      <select id="sections" data-settings-field="sections">
        ${SECTION_CHOICES.map(([value, label]) => `<option value="${value}" ${value === (me.sections || 'both') ? 'selected' : ''}>${label}</option>`).join('')}
      </select>
      <p class="muted">Only need one half of FeedStash? The other is hidden. Nothing is deleted, and feeds keep
        updating, so you can switch back any time.</p>
    </div>`;
  if (me.is_admin) {
    $('[data-group-link="admin"]', els.settings).hidden = false;
    if (state.route.id === 'admin') selectGroup('admin'); // asked for before it was known they're an admin
    $('[data-accounts-section]', els.settings).hidden = false;
    loadAccounts();
    loadSignIn(els.settings);
    loadAbout();
    loadLogs(els.settings);
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
  if (ok) toast('Password changed. Other browsers signed in to your account have been signed out.');
}

async function signOutOthers() {
  try {
    await api('POST', '/api/account/sign-out-others');
    toast('Signed out of every other browser. Apps that use a token stay connected.');
  } catch (err) {
    toast(err.message, { error: true });
  }
}

/* ---- about (admins): version, updates, where to get help */

async function loadAbout() {
  const section = $('[data-about-section]', els.settings);
  if (!section) return;
  section.hidden = false;
  const { version } = state.tree;
  const line = $('[data-about-version]', section);
  line.textContent = version === 'dev' ? 'Development build' : `Version ${version}`;
  $('[data-about-mail]', section).href = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(`FeedStash ${version}`)}`;
  let info;
  try {
    info = await api('GET', '/api/admin/updates');
  } catch {
    return;
  }
  if (!line.isConnected) return;
  if (info.latest) {
    line.innerHTML = `Version ${esc(version)} · <a href="${esc(info.latest_url)}" target="_blank" rel="noopener">${esc(info.latest)} is out</a>`;
  } else if (version !== 'dev') {
    line.textContent = `Version ${version} · up to date`;
  }
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
            <td class="row-actions"><button class="btn btn-sm" data-settings="rename-token" data-id="${token.id}" data-name="${esc(token.clientName)}">Rename</button>
              <button class="btn btn-sm" data-settings="revoke" data-id="${token.id}" data-name="${esc(token.clientName)}">Revoke</button></td>
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

/** A new token for the phone or iPad app, as a QR code it can scan to connect without typing anything. */
async function connectPhone() {
  let created;
  try {
    created = await api('POST', '/api/tokens/connect', { clientName: 'Phone or iPad' });
  } catch (err) {
    toast(err.message, { error: true });
    return;
  }
  loadTokens();
  const [first] = created.codes;
  const choices = created.codes.length > 1
    ? `<label>Server address <small>(the one the app will use; your https address works away from home too)</small>
        <select data-connect-server>${created.codes.map((code, i) => `<option value="${i}">${esc(code.server)}</option>`).join('')}</select></label>`
    : '';
  await modal({
    title: 'Connect a phone or iPad',
    confirmText: 'Done',
    // The QR codes are SVG the server drew from the link; nothing anyone typed is in them.
    html: `<p>Point the iPhone or iPad Camera at this code, or tap <b>Scan QR code</b> in the FeedStash app's
        Settings. It connects the app with a new token, “${esc(created.clientName)}”, that you can revoke here.
        The code is shown only once.</p>
      ${choices}
      <div class="qr-code" data-qr>${first.svg}</div>
      <details class="connect-manual"><summary>Type it in instead</summary>
        <label>Server address<input type="text" readonly value="${esc(first.server)}" data-connect-address></label>
        <label>Token<input type="text" readonly value="${esc(created.token)}"></label>
        <p><button type="button" class="btn btn-sm" data-copy="${esc(created.token)}">${icon('copy')}Copy token</button></p>
      </details>`,
    onOpen: (dialog) => {
      dialog.addEventListener('click', (e) => {
        const button = e.target.closest('[data-copy]');
        if (button) copyFrom(button);
      });
      dialog.addEventListener('change', (e) => {
        if (!e.target.matches('[data-connect-server]')) return;
        const code = created.codes[Number(e.target.value)];
        $('[data-qr]', dialog).innerHTML = code.svg;
        $('[data-connect-address]', dialog).value = code.server;
      });
    },
  });
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

/** A clearer name for a token ("iPhone", "Work laptop's Firefox"), so you know which one to revoke later. */
async function renameToken(id, name) {
  const renamed = await promptDialog({
    title: 'Rename token',
    label: 'App name',
    value: name,
    onSubmit: (clientName) => api('PATCH', `/api/tokens/${id}`, { clientName }),
  });
  if (renamed) loadTokens();
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

const SECTION_CHOICES = [['both', 'Feeds and Stash'], ['feeds', 'Feeds only'], ['stash', 'Stash only']];

/** Shows only the Settings sections for the halves of the app this person uses. */
function applySettingsSections() {
  $$('[data-only="feeds"]', els.settings).forEach((el) => { el.hidden = !showsFeeds(); });
  $$('[data-only="stash"]', els.settings).forEach((el) => { el.hidden = !showsStash(); });
  // Importing is for both halves, so the Feeds group stays, called Import for someone who only uses the stash.
  const feedsLink = $('[data-group-link="feeds"]', els.settings);
  if (feedsLink) feedsLink.textContent = showsFeeds() ? 'Feeds' : 'Import';
  const stashLink = $('[data-group-link="stash"]', els.settings);
  if (stashLink) stashLink.hidden = !showsStash();
}

async function saveSections(select) {
  try {
    me = await api('PATCH', '/api/account', { sections: select.value });
  } catch (err) {
    toast(err.message, { error: true });
    select.value = state.sections;
    return;
  }
  state.sections = me.sections;
  applySections();
  applySettingsSections();
  renderNav();
  toast({ both: 'Showing feeds and the stash', feeds: 'Showing feeds only', stash: 'Showing the stash only' }[me.sections]);
}

async function saveReadRetention(select) {
  const days = Number(select.value);
  try {
    me = await api('PATCH', '/api/account', { read_retention_days: days });
    const label = READ_RETENTION_CHOICES.find(([value]) => value === days)?.[1] || `${days} days`;
    toast(days ? `Read articles will be deleted ${label} after you read them` : 'Read articles are kept until the server clears old articles');
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireSettings() {
  wireImport(els.settings);
  wireMail(els.settings);
  wireLogs(els.settings);
  wireSignIn(els.settings);
  wireRules(els.settings);
  wireTagSettings(els.settings, async () => {
    try {
      state.stash.summary = await api('GET', '/api/stash/summary'); // smart lists a tag change edited or removed
      renderNav();
    } catch {
      /* the sidebar catches up on the next refresh */
    }
  });
  els.settings.addEventListener('change', (e) => {
    if (e.target.matches('[data-settings-field=read-retention]')) saveReadRetention(e.target);
    if (e.target.matches('[data-settings-field=sections]')) saveSections(e.target);
    if (e.target.matches('[data-settings-field=theme-mode]')) setTheme({ mode: e.target.value });
    if (e.target.matches('[data-settings-field=mark-on-scroll]')) setPref('markOnScroll', e.target.value === 'on');
  });
  els.settings.addEventListener('click', (e) => {
    const copy = e.target.closest('[data-copy]');
    if (copy) return copyFrom(copy);
    const swatch = e.target.closest('.swatch[data-scheme]'); // <html> carries data-scheme too
    if (swatch) return chooseScheme(swatch.dataset.scheme);
    const button = e.target.closest('[data-settings]');
    if (!button) return;
    const { id, name } = button.dataset;
    switch (button.dataset.settings) {
      case 'new-token': newToken(); break;
      case 'connect-phone': connectPhone(); break;
      case 'rename-token': renameToken(Number(id), name); break;
      case 'revoke': revoke(Number(id), name); break;
      case 'change-password': changePassword(); break;
      case 'sign-out-others': signOutOthers(); break;
      case 'shortcuts': showShortcuts(); break;
      case 'new-account': newAccount(); break;
      case 'set-password': setPassword(Number(id), name); break;
      case 'toggle-admin': toggleAdmin(Number(id), button.dataset.admin === 'true', name); break;
      case 'remove-account': removeAccount(Number(id), name); break;
    }
  });
}
