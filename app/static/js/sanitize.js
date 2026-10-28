/* Article HTML sanitizer. The server already sanitizes with feedparser; this is a second layer. */

const ALLOWED_TAGS = new Set(('a abbr audio b bdi bdo blockquote br caption cite code col colgroup dd del details dfn div dl dt em ' +
  'figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p picture pre q rp rt ruby s samp small source span ' +
  'strong sub summary sup table tbody td tfoot th thead time tr track u ul var video wbr').split(' '));
const DROP_TAGS = new Set(('script style iframe frame frameset object embed applet form input button textarea select option ' +
  'noscript template svg math link meta base title head').split(' '));
const ALLOWED_ATTRS = new Set(['href', 'src', 'srcset', 'alt', 'title', 'width', 'height', 'colspan', 'rowspan',
  'datetime', 'cite', 'controls', 'poster', 'type', 'sizes', 'media', 'start', 'reversed', 'lang', 'dir', 'open']);
const URL_ATTRS = new Set(['href', 'src', 'poster', 'cite']);
/* The server marks galleries and video links (app/feeds/embeds.py) with these; no other class is kept. */
const ALLOWED_CLASSES = new Set(['fs-gallery', 'fs-video']);

function safeUrl(value, allowDataImage) {
  // Browsers ignore whitespace/control characters inside a scheme ("java\tscript:"), so strip them first.
  const v = value.replace(/[\s\u0000-\u001f]/g, '');
  if (/^(https?:|mailto:)/i.test(v) || v.startsWith('//')) return true;
  if (allowDataImage && /^data:image\/(png|gif|jpe?g|webp|avif);/i.test(v)) return true;
  return !/^[a-z][a-z0-9+.-]*:/i.test(v); // relative URL without a scheme
}

/* Chrome 156 reports a CSP violation whenever any parser sets an on… attribute, even in an inert document that never
   runs it (DOMParser, <template> and the Sanitizer API alike). So handler names inside tags are renamed first,
   skipping every attribute value, quoted or not; the walk below removes them like any other unlisted attribute. This
   only quiets the report: the walk is what keeps them out. */
const TAG = /<[a-z][^>"']*(?:(?:"[^"]*"|'[^']*')[^>"']*)*>?/gi;
const HANDLER_NAME = /(=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))|(?<=["'\s/])on(?=[a-z])/gi;

function renameHandlers(html) {
  return html.replace(TAG, (tag) => tag.replace(HANDLER_NAME, (match, value) => value ?? 'data-fs-on'));
}

/** Returns a DocumentFragment with only allowlisted tags and attributes; links open in a new tab. */
export function sanitize(html) {
  const doc = new DOMParser().parseFromString(`<!doctype html><body>${renameHandlers(html)}</body>`, 'text/html');
  const walk = (node) => {
    for (const child of [...node.children]) {
      const tag = child.tagName.toLowerCase();
      if (DROP_TAGS.has(tag)) {
        child.remove();
        continue;
      }
      walk(child);
      if (!ALLOWED_TAGS.has(tag)) {
        child.replaceWith(...child.childNodes);
        continue;
      }
      for (const attr of [...child.attributes]) {
        const name = attr.name.toLowerCase();
        if (name === 'class') {
          if (!ALLOWED_CLASSES.has(attr.value.trim())) child.removeAttribute(attr.name);
        } else if (!ALLOWED_ATTRS.has(name)) child.removeAttribute(attr.name);
        else if (URL_ATTRS.has(name) && !safeUrl(attr.value, tag === 'img')) child.removeAttribute(attr.name);
        else if (name === 'srcset' && /(javascript|data):/i.test(attr.value)) child.removeAttribute(attr.name);
      }
      if (tag === 'a') {
        child.setAttribute('target', '_blank');
        child.setAttribute('rel', 'noopener noreferrer');
      } else if (tag === 'img') {
        child.setAttribute('loading', 'lazy');
      }
    }
  };
  walk(doc.body);
  const fragment = document.createDocumentFragment();
  fragment.append(...doc.body.childNodes);
  return fragment;
}
