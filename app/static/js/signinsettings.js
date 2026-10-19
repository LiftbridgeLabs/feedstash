/* Settings → Sign-in (admins): Google or your own single sign-on (Pocket ID, Authentik, Authelia…) next to
   passwords, and who may sign in with them. */

import { api } from './api.js';
import { modal, toast } from './dialogs.js';
import { icon } from './icons.js';
import { $, esc } from './util.js';

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

function providerRow(provider) {
  const kind = provider.kind === 'google' ? 'Google' : `OpenID Connect · ${esc(host(provider.issuer))}`;
  let status = provider.enabled ? '' : 'Turned off.';
  if (provider.secret_unreadable) status = '<span class="status-err">Enter the client secret again: it was saved with a different SECRET_KEY.</span>';
  if (provider.from_server_settings) status = 'Set in the server\'s settings, so it can only be changed there.';
  const actions = provider.from_server_settings ? '' : `
      <div class="org-actions">
        <button class="btn btn-sm" data-signin="edit" data-id="${provider.id}">${icon('sliders')}Edit</button>
        <button class="btn btn-sm" data-signin="toggle" data-id="${provider.id}">${provider.enabled ? 'Turn off' : 'Turn on'}</button>
        <button class="btn btn-sm" data-signin="remove" data-id="${provider.id}">Remove</button>
      </div>`;
  return `
    <div class="setting-row">
      <span><b>${esc(provider.name)}</b> <span class="muted">${kind}</span></span>
      ${actions}
      ${status ? `<p class="muted">${status}</p>` : ''}
    </div>`;
}

function render(section) {
  $('[data-signin-list]', section).innerHTML = overview.providers.length
    ? overview.providers.map(providerRow).join('')
    : '<p class="muted">Only passwords so far.</p>';
  const fromServer = [...overview.server_allowed_emails, ...overview.server_allowed_domains];
  $('[data-signin-allowed]', section).innerHTML = `
    <form class="mail-form" data-signin-allowed-form>
      <p class="muted">Who can sign in this way. Accounts with a password can always sign in; everyone else has to
        be on this list. Put <code>*</code> in the addresses to let in anyone your sign-in provider lets in.</p>
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
      <div data-callbacks>${callbackHTML(provider?.callback_urls || overview.callback_urls, kind)}</div>`,
    onOpen: (dialog) => {
      dialog.addEventListener('click', async (e) => {
        const button = e.target.closest('[data-copy]');
        if (!button) return;
        try {
          await navigator.clipboard.writeText(button.dataset.copy);
          button.textContent = 'Copied';
        } catch {
          button.textContent = 'Select and copy it';
        }
      });
      $('select[name=kind]', dialog)?.addEventListener('change', (e) => {
        const google = e.target.value === 'google';
        dialog.querySelectorAll('[data-oidc-only]').forEach((el) => { el.hidden = google; });
        $('[data-callbacks]', dialog).innerHTML = callbackHTML(overview.callback_urls, e.target.value);
      });
    },
    onSubmit: async (fd) => {
      const body = {
        name: (fd.get('name') || '').trim(),
        issuer: (fd.get('issuer') || '').trim(),
        client_id: (fd.get('client_id') || '').trim(),
        client_secret: fd.get('client_secret') || '',
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
  try {
    overview = await api('PATCH', `/api/admin/sign-in/providers/${provider.id}`, { enabled: !provider.enabled });
    render(section);
  } catch (err) {
    toast(err.message, { error: true });
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
    const provider = overview.providers.find((p) => String(p.id) === button.dataset.id);
    if (button.dataset.signin === 'add') editProvider(section, null);
    else if (!provider) return;
    else if (button.dataset.signin === 'edit') editProvider(section, provider);
    else if (button.dataset.signin === 'toggle') toggle(section, provider);
    else if (button.dataset.signin === 'remove') remove(section, provider);
  });
  root.addEventListener('submit', (e) => {
    if (!e.target.matches('[data-signin-allowed-form]')) return;
    e.preventDefault();
    saveAllowed(e.target, e.target.closest('[data-signin-section]'));
  });
}
