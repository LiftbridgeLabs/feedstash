importScripts('common.js');

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'save-link', title: 'Save link to FeedStash', contexts: ['link'] });
  chrome.contextMenus.create({ id: 'save-selection', title: 'Save selection to FeedStash', contexts: ['selection'] });
  chrome.contextMenus.create({ id: 'save-page', title: 'Save this page to FeedStash', contexts: ['page'] });
  chrome.contextMenus.create({ id: 'save-screenshot', title: 'Save screenshot to FeedStash', contexts: ['page'] });
});

function flashBadge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2500);
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === 'save-link') {
      await saveItem({ type: 'link', url: info.linkUrl, title: tab.title });
    } else if (info.menuItemId === 'save-selection') {
      await saveItem({ type: 'snippet', content: info.selectionText, title: tab.title, url: tab.url });
    } else if (info.menuItemId === 'save-page') {
      await saveItem({ type: 'link', url: tab.url, title: tab.title });
    } else if (info.menuItemId === 'save-screenshot') {
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
      const blob = await (await fetch(dataUrl)).blob();
      await saveItem({ type: 'screenshot', title: tab.title, url: tab.url, image: blob });
    }
    flashBadge('OK', '#3fb950');
  } catch (err) {
    console.error('FeedStash save failed:', err);
    flashBadge('!', '#e5484d');
  }
});
