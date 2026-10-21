/* Light or dark, before the page paints: "auto" follows the browser (in Firefox, its toolbar theme), or the
   choice made in Settings. Kept in localStorage too, since chrome.storage can only be read after the first paint. */
(() => {
  let choice = 'auto';
  try { choice = localStorage.getItem('appearance') || 'auto'; } catch { /* storage blocked: follow the browser */ }
  if (choice === 'light' || choice === 'dark') document.documentElement.dataset.theme = choice;
})();
