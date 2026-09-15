import PostalMime from 'postal-mime';

export default {
  async email(message, env, ctx) {
    let email;
    try {
      email = await PostalMime.parse(message.raw);
    } catch (err) {
      console.error('Failed to parse incoming email:', err);
      return;
    }

    const rawSubject = (email.subject || '(no subject)').trim();
    const { title, tags } = extractHashtags(rawSubject);
    const bodyText = (email.text || stripHtml(email.html) || '').trim();

    const fd = new FormData();
    fd.set('type', 'email');
    fd.set('title', title);
    fd.set('content', bodyText);
    fd.set('tags', JSON.stringify(tags));
    fd.set('source', 'email');

    // If the email has an image attachment, attach the first one to the note.
    const imageAttachment = (email.attachments || []).find(
      (a) => a.mimeType && a.mimeType.startsWith('image/')
    );
    if (imageAttachment) {
      const blob = new Blob([imageAttachment.content], { type: imageAttachment.mimeType });
      fd.set('image', blob, imageAttachment.filename || 'attachment.png');
    }

    const res = await fetch(`${env.FEEDSTASH_API_BASE.replace(/\/$/, '')}/api/items`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.FEEDSTASH_API_TOKEN}` },
      body: fd
    });

    if (!res.ok) {
      const body = await res.text().catch(() => '');
      console.error(`FeedStash API returned ${res.status}:`, body);
      // Optionally bounce so you notice the failure in your mail client:
      // message.setReject('FeedStash failed to save this note.');
    }
  }
};

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

function stripHtml(html) {
  if (!html) return '';
  return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}
