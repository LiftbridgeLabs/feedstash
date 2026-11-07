"""A software passkey for tests: makes and uses WebAuthn credentials the way a phone or laptop would (a P-256 key,
"none" attestation, user verified), so the server's checks run for real without a browser."""

import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, AT = 0x01, 0x04, 0x40  # authenticator data flags: user present, user verified, credential data included


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftPasskey:
    def __init__(self, origin: str, rp_id: str = "localhost"):
        self.origin, self.rp_id = origin, rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.user_handle: bytes | None = None
        self.sign_count = 0

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin,
                           "crossOrigin": False}).encode()

    def create(self, options: dict, *, origin: str | None = None, verified: bool = True) -> dict:
        """The answer to navigator.credentials.create() for the server's options."""
        self.user_handle = unb64(options["user"]["id"])
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([UP | (UV if verified else 0) | AT])
                     + struct.pack(">I", self.sign_count) + bytes(16)
                     + struct.pack(">H", len(self.credential_id)) + self.credential_id + cose)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
                             "attestationObject": b64(attestation), "transports": ["internal"]},
                "clientExtensionResults": {}}

    def get(self, options: dict, *, origin: str | None = None) -> dict:
        """The answer to navigator.credentials.get() for the server's options."""
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = (hashlib.sha256(options["rpId"].encode()).digest() + bytes([UP | UV])
                     + struct.pack(">I", self.sign_count))
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data),
                             "signature": b64(signature), "userHandle": b64(self.user_handle or b"")},
                "clientExtensionResults": {}}
