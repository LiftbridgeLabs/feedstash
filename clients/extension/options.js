async function load() {
  const { apiBaseUrl, apiToken } = await getSettings();
  document.getElementById('baseUrlInput').value = apiBaseUrl;
  document.getElementById('tokenInput').value = apiToken;
}
load();

document.getElementById('saveBtn').addEventListener('click', async () => {
  const apiBaseUrl = document.getElementById('baseUrlInput').value.trim().replace(/\/$/, '');
  const apiToken = document.getElementById('tokenInput').value.trim();
  await chrome.storage.local.set({ apiBaseUrl, apiToken });
  document.getElementById('status').textContent = 'Saved.';
});

document.getElementById('testBtn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  status.textContent = 'Testing...';
  const apiBaseUrl = document.getElementById('baseUrlInput').value.trim().replace(/\/$/, '');
  const apiToken = document.getElementById('tokenInput').value.trim();

  try {
    const health = await fetch(`${apiBaseUrl}/api/health`);
    if (!health.ok) throw new Error('Server unreachable at that URL.');

    const tagsRes = await fetch(`${apiBaseUrl}/api/tags`, {
      headers: { Authorization: `Bearer ${apiToken}` }
    });
    if (tagsRes.status === 401) throw new Error('Server reachable, but token is invalid.');
    if (!tagsRes.ok) throw new Error(`Unexpected response (${tagsRes.status}).`);

    status.textContent = 'Connected successfully.';
  } catch (err) {
    status.textContent = err.message;
  }
});
