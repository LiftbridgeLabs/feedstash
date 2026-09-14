/* JSON API client. Sends the CSRF header the server requires and turns error responses into Errors. */

export async function api(method, path, body, { keepalive = false } = {}) {
  const opts = { method, credentials: 'same-origin', keepalive, headers: { 'X-Requested-With': 'reader' } };
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
  const isJson = (res.headers.get('content-type') || '').includes('json');
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`);
  }
  return data;
}
