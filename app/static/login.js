/* The sign-in page: password sign-in, first-run setup and "Forgot password?", sent as JSON with the app's CSRF
   header. Also the invite page (/invite#<token>) and the reset page (/reset#<token>): the token is checked first,
   and sent with the form. */

import { wirePasswordReveal } from './js/reveal.js';
import { credentialJSON, passkeyErrorMessage, passkeysSupported, requestOptions } from './js/webauthn.js';

wirePasswordReveal();

const ENDPOINTS = {
  setup: '/auth/setup', password: '/auth/password', invite: '/auth/invite', forgot: '/auth/forgot', reset: '/auth/reset',
  'two-step': '/auth/two-step',
};

/** The password was right and the account asks for a code too: the code form takes the page. */
function askForCode(from) {
  const codeForm = document.querySelector('form[data-login=two-step]');
  from.hidden = true;
  document.querySelectorAll('[data-forgot=open]').forEach((link) => { link.closest('.login-aside').hidden = true; });
  document.querySelectorAll('.login-or, .login-options').forEach((el) => { el.hidden = true; });
  codeForm.hidden = false;
  codeForm.querySelector('[name=code]').focus();
}
const linkToken = decodeURIComponent(location.hash.slice(1));

/* A setup link (/#setup=<token>, e.g. from a host's welcome email) fills in the setup token, so whoever opens it
   only picks their email and password. The token is after the #, which browsers never send to the server, and is
   cleared from the address bar once read. If the server refuses the token, the field shows again so it can be typed. */
function fillSetupToken() {
  const field = document.querySelector('form[data-login=setup] [name=setup_token]');
  if (!field || !linkToken.startsWith('setup=')) return;
  field.value = linkToken.slice('setup='.length);
  field.closest('label').hidden = true;
  history.replaceState(null, '', location.pathname + location.search);
}
fillSetupToken();

const post = (url, body) => fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'reader' },
  body: JSON.stringify(body),
  // A proxy's own sign-in page would otherwise look like success and send you round in a loop.
  redirect: 'manual',
});

/** "Sign in with a passkey": shown once this browser can do it and the server has given a challenge. The challenge
    is fetched before the click, so the click goes straight to the passkey (Safari wants that). */
async function wirePasskey() {
  const button = document.querySelector('[data-passkey]');
  if (!button || !passkeysSupported()) return;
  const error = document.querySelector('[data-passkey-error]');
  let options = null;
  let fetchedAt = 0;
  const load = async () => {
    options = null;
    const response = await post('/auth/passkey/options', {});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Passkeys aren't available here (${response.status})`);
    options = requestOptions(body.options);
    fetchedAt = Date.now();
  };
  try {
    await load();
  } catch {
    return;  // the button stays hidden
  }
  button.hidden = false;
  button.addEventListener('click', async () => {
    error.hidden = true;
    button.disabled = true;
    try {
      if (!options || Date.now() - fetchedAt > 4 * 60 * 1000) await load();
      const publicKey = options;
      options = null;  // each challenge is good for one try
      const credential = await navigator.credentials.get({ publicKey });
      const response = await post('/auth/passkey', { credential: credentialJSON(credential) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `Sign-in failed (${response.status})`);
      location.href = '/';
      return;
    } catch (err) {
      error.textContent = passkeyErrorMessage(err);
      error.hidden = !error.textContent;
    }
    // Ready for another try once there's a fresh challenge: a click before then would ask for a second one, and
    // the server keeps only the newest.
    load().catch(() => {}).finally(() => { button.disabled = false; });
  });
  button.dataset.ready = 'true';
}
wirePasskey();

/** A reset link that no longer works says so instead of asking for a new password. */
async function checkReset(form) {
  const problem = document.querySelector('[data-reset-problem]');
  try {
    const response = await post('/auth/reset/check', { token: linkToken });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.usable) throw new Error(body.detail || `This link can't be used (${response.status})`);
    form.hidden = false;
  } catch (err) {
    problem.textContent = err.message;
    problem.hidden = false;
  }
}

/** "Forgot password?" swaps the sign-in form for the reset-request one, carrying over the email typed so far. */
function wireForgot() {
  const signIn = document.querySelector('form[data-login=password]');
  const forgot = document.querySelector('form[data-login=forgot]');
  const link = document.querySelector('[data-forgot=open]')?.closest('.login-aside');
  if (!signIn || !forgot) return;
  const show = (wanted) => {
    signIn.hidden = wanted;
    if (link) link.hidden = wanted;
    forgot.hidden = !wanted;
    const email = (wanted ? forgot : signIn).querySelector('[name=email]');
    email.value = (wanted ? signIn : forgot).querySelector('[name=email]').value;
    email.focus();
  };
  document.addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-forgot]');
    if (!toggle) return;
    e.preventDefault();
    show(toggle.dataset.forgot === 'open');
  });
}
wireForgot();

/** An invite link that no longer works says so instead of showing the form; one for an address fills it in. */
async function checkInvite(form) {
  const problem = document.querySelector('[data-invite-problem]');
  try {
    const response = await post('/auth/invite/check', { token: linkToken });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.usable) throw new Error(body.detail || `This invite can't be used (${response.status})`);
    if (body.email) {
      const email = form.querySelector('[name=email]');
      email.value = body.email;
      email.readOnly = true;
    }
    form.hidden = false;
  } catch (err) {
    problem.textContent = err.message;
    problem.hidden = false;
  }
}

for (const form of document.querySelectorAll('form[data-login]')) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const error = form.querySelector('[data-login-error]');
    const done = form.querySelector('[data-login-done]');
    const button = form.querySelector('[type=submit]');
    error.hidden = true;
    if (done) done.hidden = true;
    button.disabled = true;
    try {
      const fields = Object.fromEntries(new FormData(form));
      if (form.dataset.login === 'invite' || form.dataset.login === 'reset') fields.token = linkToken;
      const response = await post(ENDPOINTS[form.dataset.login], fields);
      const isJson = (response.headers.get('content-type') || '').includes('json');
      if (response.ok && isJson && form.dataset.login === 'forgot') {
        done.textContent = (await response.json()).detail;
        done.hidden = false;
        button.disabled = false;
        return;
      }
      if (response.ok && isJson) {
        if ((await response.json()).two_step) {
          askForCode(form);
          button.disabled = false;
          return;
        }
        location.href = '/';
        return;
      }
      if (response.type === 'opaqueredirect' || (response.ok && !isJson)) {
        throw new Error('Something in front of FeedStash answered instead of it, probably a sign-in page. '
          + 'Sign in there first, then reload this page.');
      }
      const body = await response.json().catch(() => ({}));
      if (form.dataset.login === 'setup' && response.status === 403) {  // the token, not the other fields
        form.querySelector('[name=setup_token]')?.closest('label')?.removeAttribute('hidden');
      }
      throw new Error(body.detail || `Sign-in failed (${response.status})`);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      button.disabled = false;
    }
  });
  if (form.dataset.login === 'invite') checkInvite(form).then(() => { form.dataset.ready = 'true'; });
  else if (form.dataset.login === 'reset') checkReset(form).then(() => { form.dataset.ready = 'true'; });
  else form.dataset.ready = 'true';
}
