/* Settings → Admin → Sending email: the SMTP service that sends password-reset links and invites, and a test. */

import { api } from './api.js';
import { toast } from './dialogs.js';
import { $, esc } from './util.js';

const SECURITY = [['starttls', 'STARTTLS (usually port 587)'], ['ssl', 'SSL (usually port 465)'], ['none', 'None (a server on your own network)']];
const SOURCES = {
  app: 'Saved here.',
  server: "Set by the server's SMTP_ settings. Saving here replaces them.",
  none: 'Not set up yet.',
};

export function emailSectionHTML() {
  return `
    <div data-email-section hidden>
      <h3>Sending email</h3>
      <p class="muted">With email set up, "Forgot password?" on the sign-in page sends a reset link, and invites can
        be emailed. Any email service that offers SMTP works: SMTP2GO, Postmark, Mailgun, Gmail with an app password.</p>
      <div data-email-form><p class="muted">Loading…</p></div>
    </div>`;
}

const options = (current) => SECURITY
  .map(([value, label]) => `<option value="${value}" ${value === current ? 'selected' : ''}>${esc(label)}</option>`).join('');

/** Shows the section (admins only) and fills it in. */
export async function loadEmail(root) {
  const section = $('[data-email-section]', root);
  if (!section) return;
  section.hidden = false;
  let s;
  try {
    s = await api('GET', '/api/admin/email');
  } catch (err) {
    $('[data-email-form]', section).innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  const passwordNote = s.password_unreadable ? 'The saved password can\'t be read with this server\'s key. Enter it again.'
    : s.has_password ? 'Saved. Leave empty to keep it.' : '';
  $('[data-email-form]', section).innerHTML = `
    <form class="email-form" data-email="form" novalidate>
      <p class="muted" data-email-source>${esc(SOURCES[s.source])}${s.ready ? '' : ' Email is off until a server and From address are saved.'}</p>
      <div class="email-grid">
        <label>SMTP server<input name="host" value="${esc(s.host)}" placeholder="mail.smtp2go.com" autocomplete="off" required></label>
        <label>Port<input name="port" type="number" min="1" max="65535" value="${esc(s.port)}" required></label>
        <label>Security<select name="security">${options(s.security)}</select></label>
        <label>Username<input name="username" value="${esc(s.username)}" autocomplete="off"></label>
        <label>Password<input name="password" type="password" autocomplete="new-password"
          placeholder="${esc(passwordNote || 'The SMTP password')}"></label>
        <label>From address<input name="from_address" type="email" value="${esc(s.from_address)}" placeholder="feedstash@example.com" required></label>
        <label>From name<input name="from_name" value="${esc(s.from_name)}" placeholder="FeedStash"></label>
      </div>
      <div class="org-actions">
        <button class="btn btn-sm btn-primary" type="submit">Save</button>
        <button class="btn btn-sm" type="button" data-email="test" ${s.ready ? '' : 'disabled'}>Send a test email to me</button>
        ${s.source === 'app' ? '<button class="btn btn-sm" type="button" data-email="clear">Remove these settings</button>' : ''}
      </div>
    </form>`;
}

async function save(form) {
  const fd = new FormData(form);
  const password = fd.get('password');
  try {
    await api('PUT', '/api/admin/email', {
      host: fd.get('host').trim(),
      port: Number(fd.get('port')),
      security: fd.get('security'),
      username: fd.get('username').trim(),
      password: password ? password : null, // empty keeps the saved one
      from_address: fd.get('from_address').trim(),
      from_name: fd.get('from_name').trim(),
    });
    toast('Email settings saved. Send a test to check them.');
    loadEmail(form.closest('[data-email-section]').parentElement);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

async function sendTest(button) {
  button.disabled = true;
  const label = button.textContent;
  button.textContent = 'Sending…';
  try {
    await api('POST', '/api/admin/email/test', {});
    toast('Test email sent. Check your inbox (and the spam folder).');
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function clear(section) {
  try {
    await api('DELETE', '/api/admin/email');
    toast('Email settings removed');
    loadEmail(section.parentElement);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

export function wireEmail(root) {
  root.addEventListener('submit', (e) => {
    const form = e.target.closest('form[data-email=form]');
    if (!form) return;
    e.preventDefault();
    save(form);
  });
  root.addEventListener('click', (e) => {
    const button = e.target.closest('button[data-email]');
    if (!button) return;
    if (button.dataset.email === 'test') sendTest(button);
    if (button.dataset.email === 'clear') clear(button.closest('[data-email-section]'));
  });
}
