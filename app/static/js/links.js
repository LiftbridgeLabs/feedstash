/* Editable link rows. A stash item can hold several links, each with an optional label; the first is the primary. */

import { icon } from './icons.js';
import { $, $$, esc } from './util.js';

function rowHTML({ url = '', label = '' } = {}) {
  return `
    <div class="link-row">
      <input type="text" class="link-url" inputmode="url" placeholder="https://…" value="${esc(url)}"
             autocomplete="off" spellcheck="false" aria-label="Link URL">
      <input type="text" class="link-label" placeholder="Label (optional)" value="${esc(label || '')}"
             maxlength="1000" autocomplete="off" aria-label="Link label">
      <button type="button" class="icon-btn" data-link="up" title="Move up (the first link is the primary one)">${icon('chevron-up')}</button>
      <button type="button" class="icon-btn" data-link="remove" title="Remove this link">${icon('x')}</button>
    </div>`;
}

/** An editable list of links, always with at least one row to type into. */
export function linkRowsHTML(links = []) {
  return `
    <div class="link-rows" data-link-rows>${(links.length ? links : [{}]).map(rowHTML).join('')}</div>
    <button type="button" class="btn btn-sm link-add" data-link="add">${icon('plus')}Add another link</button>`;
}

/** Wires adding, moving up and removing rows under `root`, and splits a pasted block of URLs into rows. */
export function wireLinkRows(root) {
  const rows = $('[data-link-rows]', root);
  root.addEventListener('click', (e) => {
    const action = e.target.closest('[data-link]')?.dataset.link;
    const row = e.target.closest('.link-row');
    if (action === 'add') {
      rows.insertAdjacentHTML('beforeend', rowHTML());
      $('.link-row:last-child .link-url', rows).focus();
    } else if (action === 'up' && row?.previousElementSibling) {
      rows.insertBefore(row, row.previousElementSibling);
      $('[data-link=up]', row).focus();
    } else if (action === 'remove' && row) {
      row.remove();
      if (!rows.children.length) rows.insertAdjacentHTML('beforeend', rowHTML());
    }
  });
  rows.addEventListener('paste', (e) => {
    if (!e.target.classList.contains('link-url')) return;
    const urls = (e.clipboardData?.getData('text') || '').split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
    if (urls.length < 2) return;
    e.preventDefault();
    e.target.value = urls[0];
    e.target.closest('.link-row').insertAdjacentHTML('afterend', urls.slice(1).map((url) => rowHTML({ url })).join(''));
  });
}

/** The links typed under `root`, in order, skipping empty rows. A URL typed without a scheme gets https://. */
export function collectLinks(root) {
  return [...$$('.link-row', root)]
    .map((row) => ({ url: $('.link-url', row).value.trim(), label: $('.link-label', row).value.trim() || null }))
    .filter((link) => link.url)
    .map((link) => ({ ...link, url: /^[a-z][a-z0-9+.-]*:/i.test(link.url) ? link.url : `https://${link.url}` }));
}
