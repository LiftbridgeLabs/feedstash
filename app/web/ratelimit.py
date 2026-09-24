"""Slows down password guessing. Kept in memory, so it resets when the server restarts."""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class LoginLimiter:
    """Too many failed sign-ins for one account (from anywhere), or from one address (for any account), lock that
    account or address out until the oldest failure is older than the window."""

    def __init__(
        self, *, per_account: int = 10, per_address: int = 30, window_seconds: int = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._limits = {"account": per_account, "address": per_address}
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(address: str, email: str) -> list[tuple[str, str]]:
        return [("account", email.strip().lower()), ("address", address)]

    def _recent(self, key: tuple[str, str], now: float) -> deque[float]:
        failures = self._failures.get(key, deque())
        while failures and failures[0] <= now - self._window:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
        return failures

    def retry_after(self, address: str, email: str) -> int:
        """Seconds until this sign-in may be tried again; 0 when it may be tried now."""
        with self._lock:
            now = self._clock()
            wait = 0.0
            for key in self._keys(address, email):
                failures = self._recent(key, now)
                if len(failures) >= self._limits[key[0]]:
                    wait = max(wait, failures[0] + self._window - now)
            return math.ceil(wait)

    # Failures are keyed by whatever email was typed, so guesses spread over made-up addresses would otherwise pile
    # up forever: past this many keys, expired ones are swept, then the stalest dropped.
    MAX_KEYS = 10_000

    def record_failure(self, address: str, email: str) -> None:
        with self._lock:
            now = self._clock()
            for key in self._keys(address, email):
                self._recent(key, now)
                failures = self._failures.setdefault(key, deque())
                failures.append(now)
                while len(failures) > self._limits[key[0]]:  # only the newest `limit` matter
                    failures.popleft()
            if len(self._failures) > self.MAX_KEYS:
                self._sweep(now)

    def _sweep(self, now: float) -> None:
        for key in list(self._failures):
            self._recent(key, now)
        if len(self._failures) > self.MAX_KEYS:
            stalest = sorted(self._failures, key=lambda key: self._failures[key][-1])
            for key in stalest[: len(self._failures) - self.MAX_KEYS]:
                del self._failures[key]

    def clear_account(self, email: str) -> None:
        with self._lock:
            self._failures.pop(("account", email.strip().lower()), None)
