"""Reversible encryption for the few secrets FeedStash has to store and use again (a mailbox password).

The key is derived from the server's SECRET_KEY, so a database copied without that key keeps its secrets shut.
Decryption returns None rather than raising, and the app then asks for the secret again.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, secret_key: str):
        digest = hashlib.sha256(f"feedstash-secret-box:{secret_key}".encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str | None:
        """None when the value wasn't encrypted with this server's key (a restored backup, a changed SECRET_KEY)."""
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except (InvalidToken, ValueError):
            return None
