"""Whether a newer FeedStash release is out, asked of GitHub at most once a day and only when an admin looks."""

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.changelog import version_key

log = logging.getLogger("feedstash.updates")

REPOSITORY = "LiftbridgeLabs/feedstash"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"

CHECK_EVERY = 24 * 3600
RETRY_AFTER_FAILURE = 3600


@dataclass(frozen=True, slots=True)
class LatestRelease:
    version: str
    url: str


class UpdateChecker:
    """Remembers the latest release for a day (a failed check for an hour), so GitHub is asked rarely. The httpx
    client is passed in, so tests can use a mock transport."""

    def __init__(self, client: httpx.AsyncClient | None, *, enabled: bool):
        self._client = client
        self._enabled = enabled and client is not None
        self._latest: LatestRelease | None = None
        self._next_check = 0.0
        self._lock = asyncio.Lock()

    async def latest(self) -> LatestRelease | None:
        if not self._enabled:
            return None
        async with self._lock:
            if time.monotonic() >= self._next_check:
                await self._check()
            return self._latest

    async def _check(self) -> None:
        try:
            response = await self._client.get(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"})
            response.raise_for_status()
            data = response.json()
            version = str(data.get("tag_name") or "").removeprefix("v")
            if version_key(version) is None:
                raise ValueError(f"unexpected tag {data.get('tag_name')!r}")
            url = str(data.get("html_url") or "")
            if not url.startswith(f"https://github.com/{REPOSITORY}/"):
                url = f"{RELEASES_URL}/tag/v{version}"
            self._latest = LatestRelease(version, url)
            self._next_check = time.monotonic() + CHECK_EVERY
        except (httpx.HTTPError, ValueError, AttributeError) as err:
            log.info("Couldn't check for a newer FeedStash release: %s", err)
            self._next_check = time.monotonic() + RETRY_AFTER_FAILURE

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def create_checker(*, enabled: bool, version: str) -> UpdateChecker:
    """No client at all when it's turned off or on a development build, which has nothing to compare."""
    if not enabled or version_key(version) is None:
        return UpdateChecker(None, enabled=False)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        follow_redirects=False,
        headers={"User-Agent": f"FeedStash/{version}"},
    )
    return UpdateChecker(client, enabled=True)


def is_newer(latest: str, current: str) -> bool:
    new, now = version_key(latest), version_key(current)
    return new is not None and now is not None and new > now
