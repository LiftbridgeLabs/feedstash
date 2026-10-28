/* The sign-in page: password sign-in and first-run setup, sent as JSON with the app's CSRF header. Also the invite
   page (/invite#<token>): the token is checked first, and sent with the form. */

const ENDPOINTS = { setup: '/auth/setup', password: '/auth/password', invite: '/auth/invite' };
const inviteToken = decodeURIComponent(location.hash.slice(1));

/** An invite link that no longer works says so instead of showing the form; one for an address fills it in. */
async function checkInvite(form) {
  const problem = document.querySelector('[data-invite-problem]');
  try {
    const response = await fetch('/auth/invite/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'reader' },
      body: JSON.stringify({ token: inviteToken }),
      redirect: 'manual',
    });
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
    const button = form.querySelector('[type=submit]');
    error.hidden = true;
    button.disabled = true;
    try {
      const fields = Object.fromEntries(new FormData(form));
      if (form.dataset.login === 'invite') fields.token = inviteToken;
      const response = await fetch(ENDPOINTS[form.dataset.login], {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'reader' },
        body: JSON.stringify(fields),
        // A proxy's own sign-in page would otherwise look like success and send you round in a loop.
        redirect: 'manual',
      });
      const isJson = (response.headers.get('content-type') || '').includes('json');
      if (response.ok && isJson) {
        location.href = '/';
        return;
      }
      if (response.type === 'opaqueredirect' || (response.ok && !isJson)) {
        throw new Error('Something in front of FeedStash answered instead of it, probably a sign-in page. '
          + 'Sign in there first, then reload this page.');
      }
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Sign-in failed (${response.status})`);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      button.disabled = false;
    }
  });
  if (form.dataset.login === 'invite') checkInvite(form).then(() => { form.dataset.ready = 'true'; });
  else form.dataset.ready = 'true';
}
