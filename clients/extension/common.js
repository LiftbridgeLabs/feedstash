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

async function saveItem(fields) {
  const { apiBaseUrl, apiToken } = await getSettings();
  if (!apiBaseUrl || !apiToken) {
    throw new Error('Set your FeedStash server URL and token in the extension’s Settings first.');
  }

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

  const res = await fetch(`${apiBaseUrl.replace(/\/$/, '')}/api/items`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiToken}` },
    body: fd
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Save failed (${res.status})`);
  }
  return res.json();
}
