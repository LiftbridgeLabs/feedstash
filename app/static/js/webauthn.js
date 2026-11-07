/* Passkeys in the browser. The server's WebAuthn options carry bytes as base64url text; the browser wants bytes, and
   its answer goes back as base64url text. Written out by hand rather than with PublicKeyCredential's own JSON helpers,
   which older Safari doesn't have. */

function toBytes(text) {
  const b64 = text.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}

function toText(buffer) {
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Whether this browser, on this address, can use passkeys at all (https or localhost, and WebAuthn). */
export function passkeysSupported() {
  return Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);
}

const withIds = (list) => (list || []).map((c) => ({ ...c, id: toBytes(c.id) }));

export function creationOptions(json) {
  return { ...json, challenge: toBytes(json.challenge), user: { ...json.user, id: toBytes(json.user.id) },
    excludeCredentials: withIds(json.excludeCredentials) };
}

export function requestOptions(json) {
  return { ...json, challenge: toBytes(json.challenge), allowCredentials: withIds(json.allowCredentials) };
}

/** A new or used passkey's answer, as JSON for the server. */
export function credentialJSON(credential) {
  const r = credential.response;
  const response = { clientDataJSON: toText(r.clientDataJSON) };
  if (r.attestationObject) {
    response.attestationObject = toText(r.attestationObject);
    response.transports = r.getTransports ? r.getTransports() : [];
  }
  if (r.authenticatorData) {
    response.authenticatorData = toText(r.authenticatorData);
    response.signature = toText(r.signature);
    if (r.userHandle) response.userHandle = toText(r.userHandle);
  }
  return {
    id: credential.id, rawId: toText(credential.rawId), type: credential.type, response,
    authenticatorAttachment: credential.authenticatorAttachment || undefined,
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
  };
}

/** What to tell the person when the browser's passkey step fails; '' when they just closed it. */
export function passkeyErrorMessage(err) {
  if (err?.name === 'NotAllowedError' || err?.name === 'AbortError') return '';
  if (err?.name === 'InvalidStateError') return 'This device already has a passkey for your account.';
  if (err?.name === 'SecurityError') return "Passkeys don't work at this address. Use your server's https address.";
  return err?.message || 'The passkey step failed. Try again.';
}
