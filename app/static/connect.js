/* The page the "Connect a phone or iPad" QR code opens: turns the server and token after the # into the app's own
   link. They never reach the server (browsers don't send what follows the #). */

const params = new URLSearchParams(location.hash.slice(1));
const server = params.get('server');
const token = params.get('token');
const open = document.querySelector('[data-connect-open]');
const text = document.querySelector('[data-connect-text]');

if (server && token) {
  open.href = `feedstash://connect?${new URLSearchParams({ server, token })}`;
  open.hidden = false;
  text.textContent = `Tap Open in FeedStash to connect the app to ${server}.`;
  // Don't leave the token in the address bar or history.
  history.replaceState(null, '', location.pathname);
} else {
  text.textContent = 'This link is missing its server or token. Make a new code in FeedStash under Settings → '
    + 'Connected apps → Connect a phone or iPad.';
}
