// The worker's bounce paths and a save, against a fake FeedStash: `npm test` (Node's own test runner).
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

const ENV = { FEEDSTASH_API_BASE: 'https://stash.test/', FEEDSTASH_API_TOKEN: 'secret-token', ALLOWED_SENDERS: 'me@example.com' };
const MIME = 'From: me@example.com\r\nTo: stash@mine.test\r\nSubject: Read this #later\r\nContent-Type: text/plain\r\n\r\n' +
  'Worth a look: https://example.org/article\r\n';

function message({ from = 'me@example.com', to = 'stash@mine.test', raw = MIME, rawSize } = {}) {
  const bytes = new TextEncoder().encode(raw);
  return {
    from, to, rawSize: rawSize ?? bytes.length, rejected: null,
    raw: new ReadableStream({ start(c) { c.enqueue(bytes); c.close(); } }),
    setReject(reason) { this.rejected = reason; },
  };
}

let calls;
function answer(fn) {
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return fn(); };
}
const json = (status = 201) => new Response('{"id": 1}', { status, headers: { 'content-type': 'application/json' } });

beforeEach(() => { calls = []; answer(json); console.error = () => {}; console.log = () => {}; });

test('saves the message with its title, tags and links', async () => {
  const msg = message();
  await worker.email(msg, ENV);
  assert.equal(msg.rejected, null);
  assert.equal(calls[0].url, 'https://stash.test/api/items');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer secret-token');
  const body = calls[0].init.body;
  assert.equal(body.get('title'), 'Read this');
  assert.deepEqual(JSON.parse(body.get('tags')), ['later']);
  assert.deepEqual(JSON.parse(body.get('links')), ['https://example.org/article']);
});

test('bounces when the server address or token is missing', async () => {
  const msg = message();
  await worker.email(msg, { ...ENV, FEEDSTASH_API_BASE: '' });
  assert.match(msg.rejected, /not set up/);
  assert.equal(calls.length, 0);
});

test('bounces when the server cannot be reached, without naming the token', async () => {
  globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
  const msg = message();
  await worker.email(msg, ENV);
  assert.match(msg.rejected, /could not be reached/);
  assert.doesNotMatch(msg.rejected, /secret-token|stash\.test/);
});

test('bounces anything unexpected instead of dropping it', async () => {
  const original = globalThis.FormData;
  globalThis.FormData = class { set() { throw new Error('boom'); } };
  try {
    const msg = message();
    await worker.email(msg, ENV);
    assert.match(msg.rejected, /could not save this message/);
  } finally {
    globalThis.FormData = original;
  }
});

test('bounces a redirect to a sign-in page, an error and a page that is not JSON', async () => {
  answer(() => new Response('', { status: 302, headers: { location: 'https://login.test' } }));
  let msg = message(); await worker.email(msg, ENV); assert.match(msg.rejected, /sign-in page/);
  answer(() => new Response('nope', { status: 401 }));
  msg = message(); await worker.email(msg, ENV); assert.match(msg.rejected, /HTTP 401/);
  answer(() => new Response('<html>', { status: 200, headers: { 'content-type': 'text/html' } }));
  msg = message(); await worker.email(msg, ENV); assert.match(msg.rejected, /page, not an item/);
});

test('ALLOWED_SENDERS takes addresses, @domains and bare domains', async () => {
  for (const [list, from, ok] of [
    ['me@example.com', 'me@example.com', true],
    ['me@example.com', 'someone@example.com', false],
    ['@example.com', 'someone@example.com', true],
    ['example.com', 'someone@example.com', true],
    ['example.com', 'someone@notexample.com', false],
    ['@example.com', '', false],
    ['*', 'anyone@else.test', true],
  ]) {
    const msg = message({ from });
    await worker.email(msg, { ...ENV, ALLOWED_SENDERS: list });
    assert.equal(msg.rejected === null, ok, `${list} / ${from}`);
  }
});

test('ADDRESS_SECRET must be the + part of the address', async () => {
  const env = { ...ENV, ADDRESS_SECRET: 'k7q2x9' };
  for (const [to, ok] of [
    ['stash+k7q2x9@mine.test', true],
    ['Stash+K7Q2X9@mine.test', true],
    ['stash@mine.test', false],
    ['stash+wrong@mine.test', false],
    ['stash+k7q2x9extra@mine.test', false],
  ]) {
    const msg = message({ to });
    await worker.email(msg, env);
    assert.equal(msg.rejected === null, ok, to);
    if (!ok) assert.match(msg.rejected, /does not accept mail/);
  }
});

test('bounces a message over 15 MB before reading it', async () => {
  const msg = message({ rawSize: 16 * 1024 * 1024 });
  await worker.email(msg, ENV);
  assert.match(msg.rejected, /too large/);
  assert.equal(calls.length, 0);
});
