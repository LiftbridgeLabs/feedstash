async function getSettings() {
  const { apiBaseUrl, apiToken } = await chrome.storage.local.get(['apiBaseUrl', 'apiToken']);
  return { apiBaseUrl: apiBaseUrl || '', apiToken: apiToken || '' };
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
