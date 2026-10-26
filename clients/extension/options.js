async function load() {
  const { apiBaseUrl, apiToken } = await getSettings();
  document.getElementById('baseUrlInput').value = apiBaseUrl;
  document.getElementById('tokenInput').value = apiToken;
  let appearance = 'auto';
  try { appearance = localStorage.getItem('appearance') || 'auto'; } catch { /* storage blocked */ }
  document.getElementById('appearanceSelect').value = appearance;
  // Opened by a right-click save that couldn't go through yet: say what's missing.
  const status = document.getElementById('status');
  if (!apiBaseUrl || !apiToken) {
    status.textContent = 'Enter your server address and a token, then click Save, to start saving to FeedStash.';
  } else if (!(await serverAllowed(apiBaseUrl))) {
    status.textContent = 'Click Save and choose Allow, so FeedStash Capture can reach your server.';
  }
}
load();

/* Applies at once, here and in the popup next time it opens. Firefox's "Match the browser" follows its toolbar
   theme, not the Website appearance setting, so a light toolbar theme gives a light popup. */
document.getElementById('appearanceSelect').addEventListener('change', (e) => {
  const choice = e.target.value;
  try { localStorage.setItem('appearance', choice); } catch { /* storage blocked: stays on the browser's */ }
  if (choice === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
});

/** The extension may reach only the sites you allow, and your server is the only one it needs: the page you save is
    read with the one-time access a click on its button or menu gives. Asked for straight from the click, which is
    when a browser shows the prompt. */
async function allowServer(apiBaseUrl) {
  const granted = await chrome.permissions.request({ origins: [serverPattern(apiBaseUrl)] });
  if (!granted) throw new Error('FeedStash needs your permission to reach your server. Click again and choose Allow.');
}

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
    await allowServer(apiBaseUrl);
    const apiToken = document.getElementById('tokenInput').value.trim();
    const before = await getSettings();
    await chrome.storage.local.set({ apiBaseUrl, apiToken });
    // Folder ids belong to one server and account: another one's folder 3 isn't this one's.
    if (before.apiBaseUrl !== apiBaseUrl || before.apiToken !== apiToken) await chrome.storage.local.remove('lastFolderId');
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
    await allowServer(apiBaseUrl);
    const health = await feedstashFetch(`${apiBaseUrl}/api/health`);
    if (!health.ok) throw new Error('That address answered, but not as FeedStash.');
    // Only a real, signed-in answer counts: a proxy's login page would have been caught above.
    await feedstashFetch(`${apiBaseUrl}/api/tags`, { headers: { Authorization: `Bearer ${apiToken}` } });
    status.textContent = `Connected to FeedStash ${health.version || ''}.`.replace(' .', '.') + warning;
  } catch (err) {
    status.textContent = err.message;
  }
});
