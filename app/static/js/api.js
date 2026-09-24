/* JSON API client. Sends the CSRF header the server requires and turns error responses into Errors.

   A reverse proxy with its own sign-in (Pangolin, Authentik, Cloudflare Access...) answers an expired session with a
   redirect to its login page. Followed, that looks like a 200 with HTML, so redirects aren't followed, and anything
   that isn't JSON (apart from an empty 204) is an error rather than "no data". */

export const PROXY_IN_THE_WAY = 'Something in front of FeedStash answered instead of it, probably a sign-in page. '
  + 'Reload the page to sign in again.';

export async function api(method, path, body, { keepalive = false } = {}) {
  const opts = {
    method, credentials: 'same-origin', keepalive, redirect: 'manual', headers: { 'X-Requested-With': 'reader' },
  };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error('Network error — is the server running?');
  }
  if (res.status === 401) {
    location.href = '/';
    throw new Error('Signed out');
  }
  if (res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) throw new Error(PROXY_IN_THE_WAY);
  const isJson = (res.headers.get('content-type') || '').includes('json');
  if (res.ok && !isJson) {
    if (res.status === 204) return null;
    throw new Error(PROXY_IN_THE_WAY);
  }
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`);
  }
  return data;
}
