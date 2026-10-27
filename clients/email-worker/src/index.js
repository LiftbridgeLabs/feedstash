import PostalMime from 'postal-mime';

const MAX_LINKS = 10;
// Links every newsletter carries that nobody wants as the saved page.
const BORING_LINK = /unsubscribe|list-manage|mailchi\.mp\/.*unsub|preferences|privacy|\.gif($|\?)/i;

// Bigger messages are bounced before parsing: a heavy multipart message can run past a free Worker's CPU limit.
const MAX_RAW_BYTES = 15 * 1024 * 1024;
// The server keeps at most 1,000,000 characters of an item's text.
const MAX_CONTENT = 1_000_000;

export default {
  async email(message, env) {
    // Every failure bounces the message (setReject), so it stays in your outbox instead of vanishing. The catch is
    // the last resort for anything unexpected. A bounce's reason goes back to the sender, so it never names the
    // token or the server.
    try {
      await save(message, env);
    } catch (err) {
      console.error('Unexpected error saving an email:', err);
      message.setReject('FeedStash could not save this message. Nothing was saved; try again later.');
    }
  },
};

async function save(message, env) {
  const base = (env.FEEDSTASH_API_BASE || '').trim().replace(/\/$/, '');
  const token = (env.FEEDSTASH_API_TOKEN || '').trim();
  if (!base || !token) {
    console.error('FEEDSTASH_API_BASE and FEEDSTASH_API_TOKEN must both be set on the worker.');
    message.setReject('This FeedStash email address is not set up yet.');
    return;
  }
  if (!addressSecretMatches(message.to, env)) {
    console.error('Rejected mail to', message.to, '- it lacks the ADDRESS_SECRET part');
    message.setReject('This address does not accept mail.');
    return;
  }
  const from = (message.from || '').trim().toLowerCase();
  const matched = senderAllowed(from, env);
  if (!matched) {
    console.error('Rejected mail from', from);
    message.setReject('This address only accepts mail from its owner.');
    return;
  }
  console.log('Accepted mail from', from, 'by', matched);
  if (message.rawSize > MAX_RAW_BYTES) {
    console.error('Rejected a message of', message.rawSize, 'bytes');
    message.setReject('This message is too large for FeedStash (15 MB at most).');
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
  const bodyText = (email.text || stripHtml(email.html) || '').trim().slice(0, MAX_CONTENT);

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

  let res;
  try {
    res = await fetch(`${base}/api/items`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
      // Don't follow redirects: a sign-in page in front of FeedStash would answer 200 and look like success.
      redirect: 'manual',
    });
  } catch (err) {
    console.error('Could not reach FeedStash:', err);
    message.setReject('FeedStash could not be reached, so this message was not saved. Try again later.');
    return;
  }

  if (res.status >= 300 && res.status < 400) {
    console.error('Redirected to', res.headers.get('location'), '— something in front of FeedStash wants a sign-in.');
    message.setReject('FeedStash is behind a sign-in page; let /api/ through so mail can be saved.');
    return;
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    console.error(`FeedStash API returned ${res.status}:`, body);
    message.setReject(`FeedStash did not save this message (HTTP ${res.status}).`);
    return;
  }
  if (!(res.headers.get('content-type') || '').includes('application/json')) {
    console.error('Expected JSON from FeedStash, got', res.headers.get('content-type'));
    message.setReject('FeedStash answered with a page, not an item; check what sits in front of it.');
  }
}

/**
 * ADDRESS_SECRET, when set, must appear as the "+" part of the address the mail was sent to: with the secret k7q2x9,
 * stash+k7q2x9@yourdomain.com is let in and plain stash@yourdomain.com is not. ALLOWED_SENDERS checks who the mail
 * says it's from, which a sender can fake; the secret can't be guessed. Cloudflare passes the "+" part through once
 * Email Routing's subaddressing is turned on.
 */
function addressSecretMatches(to, env) {
  const secret = (env.ADDRESS_SECRET || '').trim().toLowerCase();
  if (!secret) return true;
  const local = (to || '').trim().toLowerCase().split('@')[0];
  const plus = local.indexOf('+');
  return plus !== -1 && local.slice(plus + 1) === secret;
}

/**
 * ALLOWED_SENDERS is a comma-separated list. Each entry is a whole address (`you@example.com`), a whole domain
 * (`@example.com`, or `example.com`), or `*` for anyone. Empty means anyone who learns the address can post into your
 * stash. It's a spam filter, not a lock: it reads the envelope sender, which a determined sender can fake. For a
 * lock, set ADDRESS_SECRET. Returns the entry that let the mail in, or null.
 */
function senderAllowed(from, env) {
  const allowed = (env.ALLOWED_SENDERS || '')
    .split(',')
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
  if (allowed.length === 0) return '(no ALLOWED_SENDERS)';
  if (allowed.includes('*')) return '*';
  const at = from.lastIndexOf('@');
  if (at <= 0) return null;  // no sender, or no domain to match
  const domain = from.slice(at + 1);
  return allowed.find((entry) => entry === from || entry === `@${domain}` || entry === domain) || null;
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
