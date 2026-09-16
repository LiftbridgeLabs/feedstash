import PostalMime from 'postal-mime';

const MAX_LINKS = 10;
// Links every newsletter carries that nobody wants as the saved page.
const BORING_LINK = /unsubscribe|list-manage|mailchi\.mp\/.*unsub|preferences|privacy|\.gif($|\?)/i;

export default {
  async email(message, env) {
    const from = (message.from || '').trim().toLowerCase();
    if (!senderAllowed(from, env)) {
      console.error('Rejected mail from', from);
      message.setReject('This address only accepts mail from its owner.');
      return;
    }

    let email;
    try {
      email = await PostalMime.parse(message.raw);
    } catch (err) {
      console.error('Failed to parse incoming email:', err);
      message.setReject('FeedStash could not read this message.');
      return;
    }

    const { title, tags } = extractHashtags((email.subject || '(no subject)').trim());
    const bodyText = (email.text || stripHtml(email.html) || '').trim();

    const fd = new FormData();
    fd.set('type', 'email');
    fd.set('title', title);
    fd.set('content', bodyText);
    fd.set('tags', JSON.stringify(tags));
    fd.set('source', 'email');

    // Links from the message, so FeedStash can show a preview and keep a readable copy of the article.
    const links = extractLinks(email);
    if (links.length) fd.set('links', JSON.stringify(links));

    // The first image attachment, if there is one.
    const image = (email.attachments || []).find((a) => a.mimeType && a.mimeType.startsWith('image/'));
    if (image) {
      fd.set('image', new Blob([image.content], { type: image.mimeType }), image.filename || 'attachment.png');
    }

    const res = await fetch(`${env.FEEDSTASH_API_BASE.replace(/\/$/, '')}/api/items`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.FEEDSTASH_API_TOKEN}` },
      body: fd,
    });

    if (!res.ok) {
      const body = await res.text().catch(() => '');
      console.error(`FeedStash API returned ${res.status}:`, body);
      // Bounce it, so the mail stays in your outbox rather than vanishing.
      message.setReject(`FeedStash did not save this message (HTTP ${res.status}).`);
    }
  },
};

/** ALLOWED_SENDERS is a comma-separated list of addresses; empty means anyone who finds the address can post. */
function senderAllowed(from, env) {
  const allowed = (env.ALLOWED_SENDERS || '')
    .split(',')
    .map((address) => address.trim().toLowerCase())
    .filter(Boolean);
  return allowed.length === 0 || allowed.includes(from);
}

// "Cool React library #dev #tocheck" -> { title: "Cool React library", tags: ["dev","tocheck"] }
function extractHashtags(subject) {
  const tags = [];
  const cleaned = subject
    .replace(/#([\w-]+)/g, (_, tag) => {
      tags.push(tag.toLowerCase());
      return '';
    })
    .replace(/\s+/g, ' ')
    .trim();
  return { title: cleaned || subject, tags };
}

/** Web addresses from the message: the HTML's own links first, then any written out in the text. */
function extractLinks(email) {
  const found = [];
  const seen = new Set();
  const add = (url) => {
    const clean = (url || '').trim().replace(/[),.]+$/, '');
    if (!/^https?:\/\//i.test(clean) || clean.length > 2000) return;
    if (BORING_LINK.test(clean) || seen.has(clean)) return;
    seen.add(clean);
    found.push(clean);
  };
  for (const match of (email.html || '').matchAll(/href\s*=\s*["']([^"']+)["']/gi)) add(match[1]);
  for (const match of (email.text || '').matchAll(/https?:\/\/[^\s<>"']+/gi)) add(match[0]);
  return found.slice(0, MAX_LINKS);
}

function stripHtml(html) {
  if (!html) return '';
  return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}
