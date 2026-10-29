/* Settings → Sign-in (admins): Google or your own single sign-on (Pocket ID, Authentik, Authelia…) next to
   passwords, and who may sign in with them. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { $, copyText, esc } from './util.js';

let overview = null;

export function signInSectionHTML() {
  return `
    <div data-signin-section hidden>
      <h3>Sign-in</h3>
      <div class="org-head">
        <p class="muted">Let people sign in with Google or your own single sign-on, like Pocket ID, Authentik or
          Authelia. Passwords keep working.</p>
        <div class="org-actions">
          <button class="btn btn-sm btn-primary" data-signin="add">${icon('plus')}Add sign-in</button>
        </div>
      </div>
      <div data-signin-switch></div>
      <div data-signin-list><p class="muted">Loading…</p></div>
      <div data-signin-allowed></div>
    </div>`;
}

/** Shows the section (admins only) and fills it in. */
export async function loadSignIn(root) {
  const section = $('[data-signin-section]', root);
  if (!section) return;
  section.hidden = false;
  try {
    overview = await api('GET', '/api/admin/sign-in');
  } catch (err) {
    $('[data-signin-list]', section).innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  render(section);
}

const host = (url) => {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
};

const BUILT_IN = ['key', 'shield', 'lock', 'none'];

/** Dark or light text, whichever reads better on the color (as app/web/sso.py's text_color). */
function textColor(hex) {
  const channel = (i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  return luminance > 0.179 ? '#1f1f1f' : '#ffffff';
}

/** The button as the sign-in page draws it (app/web/sso.py's button_html), for the list and the preview. */
function buttonHTML({ kind, name, icon: iconName, color }) {
  const label = `<span>Sign in with ${esc(kind === 'google' ? 'Google' : name || '…')}</span>`;
  if (kind === 'google') {
    return `<span class="btn btn-lg sso-btn sso-google"><img src="/static/sso/google.svg" alt="" width="18" height="18">${label}</span>`;
  }
  let picture = '';
  if (BUILT_IN.includes(iconName || 'key')) {
    if ((iconName || 'key') !== 'none') picture = `<span class="sso-icon" style="--icon: url(/static/sso/${iconName || 'key'}.svg)"></span>`;
  } else if (/^https?:\/\//i.test(iconName)) {
    picture = `<img src="${esc(iconName)}" alt="" width="18" height="18" referrerpolicy="no-referrer">`;
  }
  const colored = /^#[0-9a-f]{6}$/i.test(color || '');
  const style = colored ? ` style="--sso-bg: ${color}; --sso-fg: ${textColor(color)}"` : '';
  return `<span class="btn btn-lg sso-btn${colored ? ' sso-colored' : ''}"${style}>${picture}${label}</span>`;
}

function providerRow(provider) {
  const kind = (provider.kind === 'google' ? 'Google' : `OpenID Connect · ${esc(host(provider.issuer))}`)
    + (provider.trust_all ? ` · ${esc(everyoneLabel(provider.name).toLowerCase())}` : ' · allowed list');
  let status = provider.enabled ? '' : 'Turned off: its button is hidden.';
  if (provider.secret_unreadable) status = '<span class="status-err">Enter the client secret again: it was saved with a different SECRET_KEY.</span>';
  if (provider.from_server_settings) {
    status = `Set in the server's settings, so it can only be changed there. ${provider.enabled ? '' : 'Turned off here.'}`;
  }
  const toggle = `<button class="btn btn-sm" data-signin="toggle" data-key="${esc(provider.key)}">${provider.enabled ? 'Turn off' : 'Turn on'}</button>`;
  // A real sign-in in a new tab that reports what happened, without signing you in as anyone else.
  const tryIt = provider.secret_unreadable ? '' : `<a class="btn btn-sm" href="/auth/login/${encodeURIComponent(provider.key)}?try=1"
        target="_blank" rel="noopener" data-signin-try title="Run a real sign-in in a new tab and see what happens">Try it</a>`;
  const actions = provider.from_server_settings ? `<div class="org-actions">${tryIt}${toggle}</div>` : `
      <div class="org-actions">
        ${tryIt}
        <button class="btn btn-sm" data-signin="edit" data-key="${esc(provider.key)}">${icon('sliders')}Edit</button>
        ${toggle}
        <button class="btn btn-sm" data-signin="remove" data-key="${esc(provider.key)}">Remove</button>
      </div>`;
  return `
    <div class="sso-row ${provider.enabled && overview.sso_enabled ? '' : 'is-off'}">
      <div class="sso-row-main">
        <div class="sso-row-button">${buttonHTML(provider)}</div>
        <span class="sso-row-kind">${kind}</span>
      </div>
      ${actions}
      ${status ? `<p class="sso-row-status">${status}</p>` : ''}
    </div>`;
}

function switchHTML() {
  if (!overview.providers.length) return '';
  return `
    <div class="setting-row">
      <label for="sso-switch">Sign-in buttons</label>
      <select id="sso-switch" data-signin-switch-field>
        <option value="on" ${overview.sso_enabled ? 'selected' : ''}>Shown</option>
        <option value="off" ${overview.sso_enabled ? '' : 'selected'}>All hidden</option>
      </select>
      <p class="muted">Hide every Google and single sign-on button at once, keeping how each is set up. Handy while
        testing; passwords keep working.</p>
    </div>`;
}

function render(section) {
  $('[data-signin-switch]', section).innerHTML = switchHTML();
  $('[data-signin-list]', section).innerHTML = overview.providers.length
    ? overview.providers.map(providerRow).join('')
    : '<p class="muted">Only passwords so far.</p>';
  const fromServer = [...overview.server_allowed_emails, ...overview.server_allowed_domains];
  $('[data-signin-allowed]', section).innerHTML = `
    <form class="mail-form" data-signin-allowed-form>
      <p class="muted">FeedStash's allowed list: who can sign in with Google, and with any sign-in set to <b>Only people
        on FeedStash's allowed list</b>. Add whole domains for a company or school. A sign-in set to <b>Everyone …
        allows</b> leaves that to your provider, and accounts with a password can always sign in.</p>
      <label>Email addresses <small>(comma separated)</small>
        <input type="text" name="emails" value="${esc(overview.allowed_emails.join(', '))}" autocomplete="off"
          placeholder="you@example.com, family@example.com"></label>
      <label>Whole domains <small>(comma separated)</small>
        <input type="text" name="domains" value="${esc(overview.allowed_domains.join(', '))}" autocomplete="off"
          placeholder="example.com"></label>
      ${fromServer.length ? `<p class="muted">Also allowed by the server's settings: ${esc(fromServer.join(', '))}</p>` : ''}
      <div class="org-actions"><button type="submit" class="btn btn-sm btn-primary">${icon('check')}Save list</button></div>
    </form>`;
}

const list = (value) => (value || '').split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);

async function saveAllowed(form, section) {
  const data = new FormData(form);
  try {
    overview = await api('PUT', '/api/admin/sign-in/allowed', {
      emails: list(data.get('emails')), domains: list(data.get('domains')),
    });
    render(section);
    toast('Saved who can sign in');
  } catch (err) {
    toast(err.message, { error: true });
  }
}

function callbackHTML(urls, kind) {
  const where = kind === 'google'
    ? 'In Google Cloud Console → APIs & Services → Credentials, create an OAuth client ID (web application) with these redirect URIs:'
    : 'At your provider, make an OIDC client (confidential, authorization code) with these redirect URIs:';
  return `
    <p class="muted" data-where>${esc(where)}</p>
    ${urls.map((url) => `
      <p class="copy-line"><code>${esc(url)}</code>
        <button type="button" class="btn btn-sm" data-copy="${esc(url)}">${icon('copy')}Copy</button></p>`).join('')}`;
}

const ICON_CHOICES = [['key', 'Key'], ['shield', 'Shield'], ['lock', 'Lock'], ['none', 'No icon'], ['link', 'An image from a link…']];

const providerName = (name) => (name || '').trim() || 'your provider';
const everyoneLabel = (name) => `Everyone ${providerName(name)} allows`;

/** Who may sign in with an OpenID Connect sign-in. Google has no such choice: anyone can have a Google account. */
function accessHTML(provider, kind) {
  const anyone = Boolean(provider?.trust_all);
  const name = provider?.name || '';
  return `
    <div data-access ${kind === 'google' ? 'hidden' : ''}>
      <label>Who can sign in with this<select name="trust_all">
        <option value="list" ${anyone ? '' : 'selected'}>Only people on FeedStash's allowed list</option>
        <option value="anyone" ${anyone ? 'selected' : ''} data-everyone>${esc(everyoneLabel(name))}</option>
      </select></label>
      <p class="muted" data-access-hint>${accessHint(name, anyone)}</p>
    </div>
    <p class="muted" data-google-access ${kind === 'google' ? '' : 'hidden'}>Google sign-in always checks FeedStash's
      allowed list, since anyone can have a Google account.</p>`;
}

function accessHint(name, anyone) {
  if (!anyone) return 'Add addresses and whole domains to the allowed list under Sign-in. Accounts with a password can always sign in.';
  return `${esc(providerName(name))} decides who gets in, for example with a user group on its FeedStash client. FeedStash doesn't check its own list for this sign-in.`;
}

function lookHTML(provider) {
  const current = provider?.icon || 'key';
  const choice = BUILT_IN.includes(current) ? current : 'link';
  const color = provider?.color || '';
  return `
    <div data-look ${provider?.kind === 'google' ? 'hidden' : ''}>
      <label>Icon<select name="icon_choice">
        ${ICON_CHOICES.map(([value, label]) => `<option value="${value}" ${value === choice ? 'selected' : ''}>${label}</option>`).join('')}
      </select></label>
      <label data-icon-link ${choice === 'link' ? '' : 'hidden'}>Image address <small>(Pocket ID, Authentik and others serve their logo)</small>
        <input type="url" name="icon_url" value="${choice === 'link' ? esc(current) : ''}" placeholder="https://id.example.com/logo.png" autocomplete="off"></label>
      <label class="check"><input type="checkbox" name="use_color" ${color ? 'checked' : ''}> Give the button a color</label>
      <input type="color" name="color" value="${esc(color || '#3b5bdb')}" aria-label="Button color" ${color ? '' : 'hidden'}>
    </div>
    <p class="muted" data-google-look ${provider?.kind === 'google' ? '' : 'hidden'}>Google's button keeps Google's own look, as its rules ask.</p>
    <div class="sso-preview"><span class="muted">Preview</span><div data-preview></div></div>`;
}

/** What the form says about the button's look, as the API wants it. */
function lookFrom(form) {
  const choice = form.elements.icon_choice?.value || 'key';
  const iconValue = choice === 'link' ? (form.elements.icon_url?.value || '').trim() || 'key' : choice;
  return { icon: iconValue, color: form.elements.use_color?.checked ? form.elements.color.value : '' };
}

/** The add / edit form. `provider` is null when adding. */
async function editProvider(section, provider) {
  const editing = Boolean(provider);
  const kind = provider?.kind || 'oidc';
  await modal({
    title: editing ? `Edit ${provider.name}` : 'Add a sign-in',
    confirmText: editing ? 'Save' : 'Add',
    busyText: 'Checking…',
    html: `
      ${editing ? '' : `<label>Type<select name="kind">
        <option value="oidc">OpenID Connect (Pocket ID, Authentik, Authelia, Keycloak…)</option>
        <option value="google">Google</option></select></label>`}
      <div data-oidc-only ${kind === 'google' ? 'hidden' : ''}>
        <label>Name on the button <small>("Sign in with …")</small>
          <input type="text" name="name" value="${esc(provider?.name || '')}" maxlength="60" placeholder="Pocket ID" autocomplete="off"></label>
      </div>
      <div data-oidc-only ${kind === 'google' ? 'hidden' : ''}>
        <label>Issuer address
          <input type="url" name="issuer" value="${esc(provider?.issuer || '')}" placeholder="https://id.example.com" autocomplete="off"></label>
      </div>
      <label>Client ID<input type="text" name="client_id" value="${esc(provider?.client_id || '')}" autocomplete="off"
        data-1p-ignore data-lpignore="true"></label>
      <label>Client secret<input type="password" name="client_secret" autocomplete="off"
        placeholder="${editing ? 'Leave empty to keep the saved one' : ''}"></label>
      <div data-callbacks>${callbackHTML(provider?.callback_urls || overview.callback_urls, kind)}</div>
      ${accessHTML(provider, kind)}
      ${lookHTML(provider)}`,
    onOpen: (dialog) => {
      const form = $('form', dialog);
      const currentKind = () => form.elements.kind?.value || kind;
      const preview = () => {
        $('[data-preview]', dialog).innerHTML = buttonHTML({
          kind: currentKind(), name: (form.elements.name.value || '').trim(), ...lookFrom(form),
        });
      };
      preview();
      dialog.addEventListener('input', (e) => {
        preview();
        if (e.target.name === 'name') {
          $('[data-everyone]', dialog).textContent = everyoneLabel(e.target.value);
          $('[data-access-hint]', dialog).innerHTML = accessHint(e.target.value, form.elements.trust_all.value === 'anyone');
        }
      });
      dialog.addEventListener('change', (e) => {
        if (e.target.name === 'kind') {
          const google = e.target.value === 'google';
          $('[data-access]', dialog).hidden = google;
          $('[data-google-access]', dialog).hidden = !google;
          if (google) form.elements.trust_all.value = 'list';
        }
        if (e.target.name === 'trust_all' || e.target.name === 'kind') {
          $('[data-access-hint]', dialog).innerHTML = accessHint(form.elements.name.value, form.elements.trust_all.value === 'anyone');
        }
        if (e.target.name === 'icon_choice') $('[data-icon-link]', dialog).hidden = e.target.value !== 'link';
        if (e.target.name === 'use_color') form.elements.color.hidden = !e.target.checked;
        if (e.target.name === 'kind') {
          const google = e.target.value === 'google';
          dialog.querySelectorAll('[data-oidc-only]').forEach((el) => { el.hidden = google; });
          $('[data-look]', dialog).hidden = google;
          $('[data-google-look]', dialog).hidden = !google;
          $('[data-callbacks]', dialog).innerHTML = callbackHTML(overview.callback_urls, e.target.value);
        }
        preview();
      });
      dialog.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-copy]');
        if (!button) return;
        button.textContent = await copyText(button.dataset.copy, button.parentElement) ? 'Copied' : 'Select and copy it';
      });
    },
    onSubmit: async (fd) => {
      const form = $('dialog.modal form');
      const currentKindAtSave = () => fd.get('kind') || kind;
      const body = {
        name: (fd.get('name') || '').trim(),
        issuer: (fd.get('issuer') || '').trim(),
        client_id: (fd.get('client_id') || '').trim(),
        client_secret: fd.get('client_secret') || '',
        trust_all: currentKindAtSave() !== 'google' && fd.get('trust_all') === 'anyone',
        ...lookFrom(form),
      };
      if (!body.client_id) throw new Error('Enter the client ID from your provider');
      if (editing) {
        if (kind === 'google') {
          delete body.name;
          delete body.issuer;
        }
        overview = await api('PATCH', `/api/admin/sign-in/providers/${provider.id}`, body);
      } else {
        if (!body.client_secret) throw new Error('Enter the client secret from your provider');
        overview = await api('POST', '/api/admin/sign-in/providers', { ...body, kind: fd.get('kind') });
      }
      render(section);
      toast(editing ? 'Sign-in saved' : 'Sign-in added. Its button is on the sign-in page now.');
    },
  });
}

async function toggle(section, provider) {
  const url = provider.from_server_settings
    ? `/api/admin/sign-in/server/${encodeURIComponent(provider.key)}`
    : `/api/admin/sign-in/providers/${provider.id}`;
  try {
    overview = await api('PATCH', url, { enabled: !provider.enabled });
    render(section);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

async function setSwitch(section, select) {
  try {
    overview = await api('PUT', '/api/admin/sign-in/switch', { enabled: select.value === 'on' });
    render(section);
    toast(overview.sso_enabled ? 'Sign-in buttons are shown again' : 'Sign-in buttons are hidden. Passwords still work.');
  } catch (err) {
    toast(err.message, { error: true });
    render(section);
  }
}

async function remove(section, provider) {
  const ok = await modal({
    title: `Remove ${provider.name}?`,
    confirmText: 'Remove',
    danger: true,
    html: `<p>Its button leaves the sign-in page. Accounts that used it stay, with everything in them, and can come
      back with a password or another sign-in for the same address.</p>`,
  });
  if (!ok) return;
  try {
    await api('DELETE', `/api/admin/sign-in/providers/${provider.id}`);
    await loadSignIn(section.parentElement);
    toast(`${provider.name} removed`);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireSignIn(root) {
  root.addEventListener('click', (e) => {
    const button = e.target.closest('[data-signin]');
    const section = button?.closest('[data-signin-section]');
    if (!section || !overview) return;
    const provider = overview.providers.find((p) => p.key === button.dataset.key);
    if (button.dataset.signin === 'add') editProvider(section, null);
    else if (!provider) return;
    else if (button.dataset.signin === 'edit') editProvider(section, provider);
    else if (button.dataset.signin === 'toggle') toggle(section, provider);
    else if (button.dataset.signin === 'remove') remove(section, provider);
  });
  root.addEventListener('change', (e) => {
    if (e.target.matches('[data-signin-switch-field]')) setSwitch(e.target.closest('[data-signin-section]'), e.target);
  });
  root.addEventListener('submit', (e) => {
    if (!e.target.matches('[data-signin-allowed-form]')) return;
    e.preventDefault();
    saveAllowed(e.target, e.target.closest('[data-signin-section]'));
  });
}
