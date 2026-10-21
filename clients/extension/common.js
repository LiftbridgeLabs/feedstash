async function getSettings() {
  const { apiBaseUrl, apiToken } = await chrome.storage.local.get(['apiBaseUrl', 'apiToken']);
  return { apiBaseUrl: apiBaseUrl || '', apiToken: apiToken || '' };
}

/**
 * The page as this browser sees it, so FeedStash can keep a readable copy of sites that turn servers away
 * (and of pages behind a sign-in). Undefined when the page can't be read: the server then fetches it itself.
 */
async function pageHtml(tabId) {
  if (!tabId) return undefined;
  try {
    const [injected] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => document.documentElement.outerHTML,
    });
    const html = injected?.result;
    return typeof html === 'string' && html.length <= 4_000_000 ? html : undefined;
  } catch {
    return undefined; // a page extensions may not read, e.g. the browser's own pages
  }
}

/** The match pattern for your server, without the port: Firefox doesn't accept one, and none covers every port. */
function serverPattern(apiBaseUrl) {
  const { protocol, hostname } = new URL(apiBaseUrl);
  return `${protocol}//${hostname}/*`;
}

const NOT_ALLOWED = 'FeedStash Capture isn\u2019t allowed to reach your server yet. Open its Settings and click Save.';

/** The extension may reach only the server you allowed in Settings, not every site, so check before calling it. */
async function serverAllowed(apiBaseUrl) {
  try {
    return await chrome.permissions.contains({ origins: [serverPattern(apiBaseUrl)] });
  } catch {
    return false; // not an address a browser can match
  }
}

const PROXY_IN_THE_WAY = 'Something in front of FeedStash answered instead of it, probably a sign-in page. '
  + 'Let /api/ through your proxy (see the FeedStash README).';

/**
 * A FeedStash API call that only counts a JSON answer from FeedStash itself as success. A reverse proxy with its own
 * sign-in answers with a redirect to its login page; followed, that would look like a 200.
 */
async function feedstashFetch(url, options = {}) {
  let res;
  try {
    res = await fetch(url, { ...options, redirect: 'manual' });
  } catch {
    throw new Error('Couldn\u2019t reach FeedStash at that address.');
  }
  if (res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) throw new Error(PROXY_IN_THE_WAY);
  const isJson = (res.headers.get('content-type') || '').includes('json');
  if (res.ok && !isJson) throw new Error(PROXY_IN_THE_WAY);
  const body = isJson ? await res.json().catch(() => ({})) : {};
  if (res.status === 401) throw new Error('FeedStash didn\u2019t accept the token. Make a new one in its Settings \u2192 Connected apps.');
  if (!res.ok) throw new Error(body.error || body.detail || `FeedStash answered with an error (${res.status})`);
  return body;
}

async function saveItem(fields) {
  const { apiBaseUrl, apiToken } = await getSettings();
  if (!apiBaseUrl || !apiToken) {
    throw new Error('Set your FeedStash server URL and token in the extension’s Settings first.');
  }
  if (!(await serverAllowed(apiBaseUrl))) throw new Error(NOT_ALLOWED);

  const fd = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null || value === '') continue;
    if (value instanceof Blob) {
      fd.append(key, value, 'screenshot.png');
    } else {
      fd.append(key, value);
    }
  }
  fd.set('source', 'extension');

  return feedstashFetch(`${apiBaseUrl.replace(/\/$/, '')}/api/items`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiToken}` },
    body: fd
  });
}
