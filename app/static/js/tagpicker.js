/* Seeing the tags you already have while you tag something, so #vibe, #vibes and #vibing don't pile up.

   attachTagPicker(input, tags) puts, under a comma-separated tags field: a sideways-scrolling row of your tags (most
   used first, narrowed to what you're typing), "All tags" for the whole list in a box that scrolls, and a nudge
   when a tag you typed looks like one you already have. */

import { esc } from './util.js';

const ROW_SIZE = 15;

/** A rough stem, so "vibe", "vibes" and "vibing", or "code" and "coding", come out the same. */
export function stem(name) {
  let word = name.toLowerCase().replace(/[^a-z0-9]+/g, '');
  for (const [suffix, replacement] of [['ies', 'y'], ['ing', ''], ['ers', ''], ['es', ''], ['ed', ''], ['er', ''], ['s', '']]) {
    if (word.length > suffix.length + 2 && word.endsWith(suffix)) {
      word = word.slice(0, -suffix.length) + replacement;
      break;
    }
  }
  return word.length > 3 && word.endsWith('e') ? word.slice(0, -1) : word;
}

function editDistanceAtMostOne(a, b) {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  let j = 0;
  let edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { i += 1; j += 1; continue; }
    edits += 1;
    if (edits > 1) return false;
    if (a.length > b.length) i += 1;
    else if (b.length > a.length) j += 1;
    else { i += 1; j += 1; }
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}

/** Whether two different tag names are probably the same idea. */
export function looksLike(a, b) {
  if (a === b) return false;
  if (stem(a) && stem(a) === stem(b)) return true;
  return Math.min(a.length, b.length) >= 4 && editDistanceAtMostOne(a, b);
}

const normalize = (text) => text.trim().replace(/^#+/, '').replace(/\s+/g, ' ').toLowerCase();
const parts = (value) => value.split(',');

/** Groups of tags that look like the same idea: each the most used of them (`into`) and the rest (`from`), which can be
    merged into it, e.g. #vibes and #vibing into #vibe. A tag is in at most one group. `tags` is most-used first. */
export function lookAlikeGroups(tags) {
  const used = new Set();
  const groups = [];
  for (const into of tags) {
    if (used.has(into.name)) continue;
    const from = tags.filter((other) => other !== into && !used.has(other.name) && other.count <= into.count
      && looksLike(other.name, into.name));
    if (!from.length) continue;
    used.add(into.name);
    from.forEach((tag) => used.add(tag.name));
    groups.push({ into, from });
  }
  return groups;
}

/** Tags for the row: matches for what's being typed (start of the name first, then look-alikes), else the most used. */
export function suggestTags(typed, tags, exclude = []) {
  const skip = new Set(exclude);
  const pool = tags.filter((tag) => !skip.has(tag.name));
  const word = normalize(typed);
  if (!word) return pool.slice(0, ROW_SIZE);
  const starts = pool.filter((tag) => tag.name.startsWith(word));
  const alike = pool.filter((tag) => !tag.name.startsWith(word) && (tag.name.includes(word) || looksLike(word, tag.name)));
  return [...starts, ...alike].slice(0, ROW_SIZE);
}

/** Returns a function that swaps in a fresher tag list (the caller fetches one: tags saved elsewhere, say from the
    phone's share sheet, aren't in the page's copy yet). */
export function attachTagPicker(input, initialTags) {
  let tags = initialTags;
  const box = document.createElement('div');
  box.className = 'tag-picker';
  input.closest('label').after(box);
  let showAll = false;

  const entered = () => parts(input.value).map(normalize).filter(Boolean);
  const typing = () => parts(input.value).at(-1);
  let known = new Map(tags.map((tag) => [tag.name, tag.count]));

  /** Puts a tag in place of the word being typed when it's a match for it (a suggestion for that word), or of an
      earlier entry when `replace` names one; otherwise adds it. */
  const choose = (name, replace = null) => {
    const list = parts(input.value).map((part) => part.trim());
    const word = normalize(list.at(-1) || '');
    if (replace != null) {
      const at = list.findIndex((part) => normalize(part) === replace);
      if (at !== -1) list[at] = name;
    } else if (!word || name.startsWith(word) || name.includes(word) || looksLike(word, name)) {
      list[list.length - 1] = name;
    } else {
      list.push(name);
    }
    const unique = [...new Set(list.filter(Boolean).map(normalize))];
    input.value = `${unique.join(', ')}, `;
    input.focus();
    render();
  };

  const chip = (tag, extra = '') => `<button type="button" class="chip" data-pick="${esc(tag.name)}" ${extra}>#${esc(tag.name)} <span>${tag.count}</span></button>`;

  function render() {
    if (!tags.length) {
      box.innerHTML = '';
      return;
    }
    const chosen = entered();
    const typed = typing();
    const row = suggestTags(typed, tags, chosen);
    const nudges = chosen
      .filter((name) => !known.has(name))
      .map((name) => [name, tags.find((tag) => looksLike(name, tag.name) && !chosen.includes(tag.name))])
      .filter(([, match]) => match);
    box.innerHTML = `
      ${row.length ? `<div class="tag-picker-row" aria-label="Your tags">${row.map((tag) => chip(tag)).join('')}</div>` : ''}
      ${nudges.map(([name, match]) => `
        <p class="tag-nudge"><span>You already have <b>#${esc(match.name)}</b> (${match.count}).</span>
          <button type="button" class="btn btn-sm" data-pick="${esc(match.name)}" data-replace="${esc(name)}">Use #${esc(match.name)}</button></p>`).join('')}
      ${tags.length > ROW_SIZE ? `<button type="button" class="btn btn-sm" data-all-tags>${showAll ? 'Hide all tags' : `All tags (${tags.length})`}</button>` : ''}
      ${showAll ? `<div class="tag-picker-all">${tags.filter((tag) => !chosen.includes(tag.name)).map((tag) => chip(tag)).join('')}</div>` : ''}`;
  }

  box.addEventListener('click', (e) => {
    const all = e.target.closest('[data-all-tags]');
    if (all) {
      showAll = !showAll;
      render();
      return;
    }
    const pick = e.target.closest('[data-pick]');
    if (pick) choose(pick.dataset.pick, pick.dataset.replace ?? null);
  });
  input.addEventListener('input', render);
  render();
  return (fresh) => {
    tags = fresh;
    known = new Map(tags.map((tag) => [tag.name, tag.count]));
    render();
  };
}
