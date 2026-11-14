"""Passkey sign-in challenges this server has handed out and not yet seen back. Kept in memory, like the sign-in
limiter: a restart forgets them, and whoever was mid sign-in presses the button again.

The browser's session cookie carries the challenge too, but a cookie is the browser's copy: an old one still holds a
challenge after it was used. This is the server's own record, so each challenge signs in at most once."""

import threading
import time
from collections.abc import Callable


class Challenges:
    # The sign-in page asks for a challenge as it opens, signed in or not: past this many, the oldest are dropped.
    MAX = 10_000

    def __init__(self, seconds: int, *, clock: Callable[[], float] = time.monotonic):
        self._seconds = seconds
        self._clock = clock
        self._issued: dict[str, float] = {}  # in the order they were handed out
        self._lock = threading.Lock()

    def issue(self, challenge: str) -> None:
        with self._lock:
            now = self._clock()
            for old in list(self._issued):
                if now - self._issued[old] <= self._seconds and len(self._issued) < self.MAX:
                    break
                del self._issued[old]
            self._issued[challenge] = now

    def use(self, challenge: str) -> bool:
        """Whether this challenge was handed out, is still in time and hasn't been used. It can't be used again."""
        with self._lock:
            issued = self._issued.pop(challenge, None)
            return issued is not None and self._clock() - issued <= self._seconds
