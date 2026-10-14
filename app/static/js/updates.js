/* For admins: what changed since the release they last saw, and a note by the version when a newer one is out. */

import { api } from './api.js';
import { $, esc } from './util.js';

/** Release notes use `code` and **bold**; everything else stays text. */
const inline = (s) => esc(s)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

// The server asks GitHub at most once a day; a tab left open asks the server again when it comes back into view.
const RECHECK_AFTER_MS = 6 * 3600 * 1000;
let lastCheck = 0;

export function watchForUpdates() {
  checkForUpdates();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && Date.now() - lastCheck > RECHECK_AFTER_MS) checkForUpdates();
  });
}

async function checkForUpdates() {
  lastCheck = Date.now();
  let info;
  try {
    info = await api('GET', '/api/admin/updates');
  } catch {
    return; // an older server, or GitHub unreachable: nothing to say
  }
  if (info.latest) showUpdateAvailable(info);
  if (info.unseen.length && !document.querySelector('dialog.whats-new')) showWhatsNew(info);
}

function showUpdateAvailable({ current, latest, latest_url: url }) {
  const shown = $('#app-version');
  const link = document.createElement('a');
  link.id = 'app-version';
  link.className = 'version update-available';
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = `v${current} · Update`;
  link.title = `FeedStash ${latest} is out (you have ${current}). Open its release notes.`;
  shown.replaceWith(link);
}

function showWhatsNew({ current, unseen, releases_url: releasesUrl }) {
  const several = unseen.length > 1;
  const dialog = document.createElement('dialog');
  dialog.className = 'modal whats-new';
  dialog.innerHTML = `
    <form method="dialog">
      <h2>What's new in FeedStash ${esc(current)}</h2>
      <p class="muted">Admins see this once after each update.</p>
      <div class="whats-new-notes">
        ${unseen.map((release) => `
          ${several ? `<h3>${esc(release.version)}</h3>` : ''}
          ${release.sections.map((section) => `
            ${section.title ? `<h4>${esc(section.title)}</h4>` : ''}
            <ul>${section.items.map((item) => `<li>${inline(item)}</li>`).join('')}</ul>`).join('')}`).join('')}
      </div>
      <div class="modal-actions">
        <a class="btn" href="${esc(releasesUrl)}" target="_blank" rel="noopener">All releases</a>
        <button class="btn btn-primary" autofocus>Got it</button>
      </div>
    </form>`;
  dialog.addEventListener('close', () => {
    dialog.remove();
    api('POST', '/api/admin/updates/seen').catch(() => {});
  });
  document.body.append(dialog);
  dialog.showModal();
}
