/* An eye button in every password field (sign-in pages and the app), to show what's typed. Fields stay
   type=password until it's clicked, so password managers fill them as before, and go back to hidden when their
   form is sent (password managers save from a hidden field). */

const EYE = '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>';
const EYE_OFF = '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>';
const svg = (paths) => `<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

function setShown(input, button, shown) {
  input.type = shown ? 'text' : 'password';
  button.innerHTML = svg(shown ? EYE_OFF : EYE);
  button.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
  button.title = button.getAttribute('aria-label');
  button.setAttribute('aria-pressed', String(shown));
}

function enhance(input) {
  if ('reveal' in input.dataset) return;
  input.dataset.reveal = '';
  const wrap = document.createElement('span');
  wrap.className = 'password-field';
  input.replaceWith(wrap);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'reveal-btn';
  wrap.append(input, button);
  setShown(input, button, false);
}

const enhanceAll = (root) => root.querySelectorAll?.('input[type=password]').forEach(enhance);

/** Call once per page; fields added later (dialogs, settings sections) get the button too. */
export function wirePasswordReveal(root = document.body) {
  enhanceAll(root);
  new MutationObserver((changes) => changes.forEach((c) => c.addedNodes.forEach((node) => {
    if (node.nodeType !== 1) return;
    if (node.matches('input[type=password]')) enhance(node); else enhanceAll(node);
  }))).observe(root, { childList: true, subtree: true });
  root.addEventListener('click', (e) => {
    const button = e.target.closest('.reveal-btn');
    if (!button) return;
    e.preventDefault(); // inside a <label>, don't also move focus around
    const input = button.parentElement.querySelector('input[data-reveal]');
    setShown(input, button, input.type === 'password');
    input.focus();
  });
  root.addEventListener('submit', (e) => {
    e.target.querySelectorAll('.password-field').forEach((wrap) => {
      setShown(wrap.querySelector('input'), wrap.querySelector('.reveal-btn'), false);
    });
  }, true);
}
