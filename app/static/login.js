/* The sign-in page: password sign-in and first-run setup, sent as JSON with the app's CSRF header. */

for (const form of document.querySelectorAll('form[data-login]')) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const error = form.querySelector('[data-login-error]');
    const button = form.querySelector('[type=submit]');
    error.hidden = true;
    button.disabled = true;
    try {
      const response = await fetch(form.dataset.login === 'setup' ? '/auth/setup' : '/auth/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'reader' },
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
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
  form.dataset.ready = 'true';
}
