let currentType = 'link';
let activeTab = null;
const FOLDER_WAIT_MS = 5000;

// Not until the popup knows its tab and folders: a click before then would save outside the remembered folder.
document.getElementById('saveBtn').disabled = true;

function updateFields() {
  document.querySelectorAll('.field[data-for]').forEach((f) => {
    f.style.display = f.dataset.for === currentType ? 'block' : 'none';
  });
}

function selectType(type) {
  document.querySelectorAll('.type-btn').forEach((b) => b.classList.toggle('active', b.dataset.type === type));
  currentType = type;
  updateFields();
}

document.querySelectorAll('.type-btn').forEach((btn) => {
  btn.addEventListener('click', () => selectType(btn.dataset.type));
});

document.getElementById('optionsLink').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

async function init() {
  try {
    await prepare();
  } finally {
    document.getElementById('saveBtn').disabled = false;
  }
}

async function prepare() {
  // Opened by "Save to FeedStash…" in the right-click menu: that tab, and the link or text clicked on.
  const pending = await chrome.runtime.sendMessage({ type: 'pending-capture' }).catch(() => null);
  const [tab] = pending?.tab ? [pending.tab] : await chrome.tabs.query({ active: true, currentWindow: true });
  activeTab = tab;
  document.getElementById('urlInput').value = tab.url || '';
  document.getElementById('titleInput').value = tab.title || '';
  if (pending?.selectionText) {
    document.getElementById('contentInput').value = pending.selectionText;
    selectType('snippet');
  } else if (pending?.linkUrl) {
    document.getElementById('urlInput').value = pending.linkUrl;
    // Left empty unless the browser gives the link's text: FeedStash then uses the linked page's title.
    document.getElementById('titleInput').value = pending.linkText || '';
  }
  updateFields();

  const { apiBaseUrl, apiToken } = await getSettings();
  if (!apiBaseUrl || !apiToken) {
    document.getElementById('status').textContent = 'Set your server URL + token in Settings first.';
    return;
  }
  if (!(await serverAllowed(apiBaseUrl))) {
    document.getElementById('status').textContent = NOT_ALLOWED;
    return;
  }
  await loadFolders(apiBaseUrl, apiToken);
}
init();

/** Your stash folders, with the one you saved to last chosen. Saving works without them if they can't be loaded, or
    take more than a few seconds. */
async function loadFolders(apiBaseUrl, apiToken) {
  const select = document.getElementById('folderSelect');
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), FOLDER_WAIT_MS);
  try {
    const folders = await feedstashFetch(`${apiBaseUrl.replace(/\/$/, '')}/api/stash/folders`, {
      headers: { Authorization: `Bearer ${apiToken}` },
      signal: timeout.signal,
    });
    const { lastFolderId } = await chrome.storage.local.get('lastFolderId');
    for (const folder of [...folders].sort((a, b) => a.position - b.position)) {
      const option = document.createElement('option');
      option.value = String(folder.id);
      option.textContent = folder.name;
      select.append(option);
    }
    if (lastFolderId && folders.some((f) => String(f.id) === lastFolderId)) select.value = lastFolderId;
  } catch {
    // Keep "No folder": an older server, or the server unreachable or slow, which saving will report.
  } finally {
    clearTimeout(timer);
  }
}

document.getElementById('saveBtn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  status.textContent = 'Saving...';
  const tags = document.getElementById('tagsInput').value;
  const title = document.getElementById('titleInput').value;
  const folderId = document.getElementById('folderSelect').value || undefined;
  await chrome.storage.local.set({ lastFolderId: folderId || '' });

  try {
    if (currentType === 'link') {
      const url = document.getElementById('urlInput').value;
      // Only the page that's open can be read, so only send it when the address is still that page's.
      const html = url === activeTab?.url ? await pageHtml(activeTab.id) : undefined;
      await saveItem({ type: 'link', url, title, tags, folderId, pageHtml: html });
    } else if (currentType === 'snippet') {
      await saveItem({
        type: 'snippet',
        content: document.getElementById('contentInput').value,
        url: activeTab.url,
        title,
        tags,
        folderId
      });
    } else if (currentType === 'screenshot') {
      const dataUrl = await chrome.tabs.captureVisibleTab(activeTab.windowId, { format: 'png' });
      const blob = await (await fetch(dataUrl)).blob();
      await saveItem({ type: 'screenshot', image: blob, url: activeTab.url, title, tags, folderId });
    }
    status.textContent = 'Saved!';
    setTimeout(() => window.close(), 700);
  } catch (err) {
    status.textContent = err.message;
  }
});
