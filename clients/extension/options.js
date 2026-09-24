async function load() {
  const { apiBaseUrl, apiToken } = await getSettings();
  document.getElementById('baseUrlInput').value = apiBaseUrl;
  document.getElementById('tokenInput').value = apiToken;
}
load();

/** The address as typed, checked: only http(s), and a warning when the token would travel unencrypted. */
function readAddress() {
  const apiBaseUrl = document.getElementById('baseUrlInput').value.trim().replace(/\/$/, '');
  let url;
  try {
    url = new URL(apiBaseUrl);
  } catch {
    throw new Error('Enter the full address, starting with https://');
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new Error('The address must start with https://');
  const warning = url.protocol === 'http:'
    ? ' Note: over http:// the token is sent unencrypted; use https:// unless this is your own network.'
    : '';
  return { apiBaseUrl, warning };
}

document.getElementById('saveBtn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  try {
    const { apiBaseUrl, warning } = readAddress();
    const apiToken = document.getElementById('tokenInput').value.trim();
    await chrome.storage.local.set({ apiBaseUrl, apiToken });
    status.textContent = 'Saved.' + warning;
  } catch (err) {
    status.textContent = err.message;
  }
});

document.getElementById('testBtn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  status.textContent = 'Testing...';
  const apiToken = document.getElementById('tokenInput').value.trim();

  try {
    const { apiBaseUrl, warning } = readAddress();
    const health = await feedstashFetch(`${apiBaseUrl}/api/health`);
    if (!health.ok) throw new Error('That address answered, but not as FeedStash.');
    // Only a real, signed-in answer counts: a proxy's login page would have been caught above.
    await feedstashFetch(`${apiBaseUrl}/api/tags`, { headers: { Authorization: `Bearer ${apiToken}` } });
    status.textContent = `Connected to FeedStash ${health.version || ''}.`.replace(' .', '.') + warning;
  } catch (err) {
    status.textContent = err.message;
  }
});
