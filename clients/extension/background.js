// Chrome runs this as a service worker, which loads common.js itself; Firefox lists both files in its manifest.
if (typeof importScripts === 'function') importScripts('common.js');

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.contextMenus.removeAll(); // an update would otherwise meet the items it made last time
  chrome.contextMenus.create({ id: 'save-link', title: 'Save link to FeedStash', contexts: ['link'] });
  chrome.contextMenus.create({ id: 'save-selection', title: 'Save selection to FeedStash', contexts: ['selection'] });
  chrome.contextMenus.create({ id: 'save-page', title: 'Save this page to FeedStash', contexts: ['page'] });
  chrome.contextMenus.create({ id: 'save-screenshot', title: 'Save screenshot to FeedStash', contexts: ['page'] });
  chrome.contextMenus.create({
    id: 'save-with-details', title: 'Save to FeedStash…', contexts: ['page', 'link', 'selection'],
  });
});

/** What "Save to FeedStash…" hands the toolbar window it opens: the tab, and the link or text right-clicked. */
let pendingCapture = null;

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message?.type !== 'pending-capture') return;
  reply(pendingCapture);
  pendingCapture = null;
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'save-with-details') openWithDetails(info, tab);
  else quickSave(info, tab);
});

/** Opens the toolbar window filled in, for adding tags, a folder or a note before saving. */
function openWithDetails(info, tab) {
  pendingCapture = {
    tab: tab && { id: tab.id, url: tab.url, title: tab.title, windowId: tab.windowId },
    linkUrl: info.linkUrl, linkText: info.linkText, selectionText: info.selectionText,
  };
  // Firefox opens it only straight from the click, before anything else is awaited. Where the toolbar window can't
  // be opened (an older browser, or the icon hidden), the same form opens in a small window of its own.
  const opened = chrome.action.openPopup ? chrome.action.openPopup() : Promise.reject(new Error('no openPopup'));
  opened.catch(() => chrome.windows.create({ url: 'popup.html', type: 'popup', width: 380, height: 640 }));
}

/** The one-click saves. Not set up yet, they open Settings, which says what's missing. */
async function quickSave(info, tab) {
  const { apiBaseUrl, apiToken } = await getSettings();
  if (!apiBaseUrl || !apiToken || !(await serverAllowed(apiBaseUrl))) {
    chrome.runtime.openOptionsPage();
    return;
  }
  try {
    let saved;
    if (info.menuItemId === 'save-link') {
      // No title: the page's own title isn't the link's, and FeedStash gives an untitled link its page's title.
      await saveItem({ type: 'link', url: info.linkUrl, title: info.linkText });
      saved = 'Link saved to FeedStash';
    } else if (info.menuItemId === 'save-selection') {
      await saveItem({ type: 'snippet', content: info.selectionText, title: tab.title, url: tab.url });
      saved = 'Note saved to FeedStash';
    } else if (info.menuItemId === 'save-page') {
      await saveItem({ type: 'link', url: tab.url, title: tab.title, pageHtml: await pageHtml(tab.id) });
      saved = 'Page saved to FeedStash';
    } else if (info.menuItemId === 'save-screenshot') {
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
      const blob = await (await fetch(dataUrl)).blob();
      await saveItem({ type: 'screenshot', title: tab.title, url: tab.url, image: blob });
      saved = 'Screenshot saved to FeedStash';
    }
    await tell(tab, saved, true);
  } catch (err) {
    console.error('FeedStash save failed:', err);
    await tell(tab, err.message, false);
  }
}

/** Says how a save went: a note on the page itself, and the toolbar badge (all there is on pages extensions can't
    touch, like the browser's own). Shown only after saving, so it's never in a saved page or screenshot. */
async function tell(tab, text, ok) {
  flashBadge(ok ? 'OK' : '!', ok ? '#187a42' : '#c5342d');
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: showNote, args: [text, ok] });
  } catch {
    // the badge will have to do
  }
}

/** Runs in the page. Text only, in its own shadow root, so neither the page nor the message can restyle the other. */
function showNote(text, ok) {
  const id = 'feedstash-capture-note';
  document.getElementById(id)?.remove();
  const host = document.createElement('div');
  host.id = id;
  const note = document.createElement('div');
  note.textContent = text;
  note.setAttribute('role', 'status');
  Object.assign(note.style, {
    position: 'fixed', right: '16px', bottom: '16px', zIndex: '2147483647', maxWidth: '360px',
    padding: '10px 14px', borderRadius: '8px', boxShadow: '0 6px 24px rgba(0, 0, 0, 0.25)',
    font: '14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    color: '#ffffff', background: ok ? '#187a42' : '#c5342d',
  });
  host.attachShadow({ mode: 'closed' }).append(note);
  document.documentElement.append(host);
  setTimeout(() => host.remove(), ok ? 3000 : 6000);
}

function flashBadge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2500);
}
