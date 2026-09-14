"""Downloads feeds over HTTP. Knows nothing about the database."""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.feeds.parser import ParsedFeed, find_feed_links, parse_feed

USER_AGENT = "Mozilla/5.0 (compatible; SelfHostedReader/1.0)"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
MAX_BYTES = 15 * 1024 * 1024
COMMON_FEED_PATHS = ("feed", "rss", "feed.xml", "rss.xml", "atom.xml", "index.xml")


class FetchError(Exception):
    """A feed couldn't be fetched. The message is meant to be shown to users."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str  # after redirects
    feed: ParsedFeed | None  # None when the server said 304 Not Modified
    etag: str | None = None
    last_modified: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.feed is None


def normalize_url(url: str) -> str:
    """Adds https:// when the scheme is missing; rejects anything but http(s)."""
    url = (url or "").strip()
    if not url:
        raise FetchError("Enter a URL")
    if not re.match(r"^https?://", url, re.I):
        if "://" in url:
            raise FetchError("Only http and https URLs are supported")
        url = "https://" + url
    if not urlparse(url).netloc:
        raise FetchError("That doesn't look like a valid URL")
    return url


def create_client(max_connections: int = 16) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
        limits=httpx.Limits(max_connections=max_connections),
    )


class Fetcher:
    """Fetches and discovers feeds with a caller-owned httpx client (so tests can pass a mock transport)."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
        """Conditional GET of a known feed URL."""
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            response, body = await self._get(url, headers)
        except httpx.HTTPError as exc:
            raise FetchError(str(exc) or exc.__class__.__name__) from exc
        if response.status_code == 304:
            return FetchResult(url=str(response.url), feed=None, etag=etag, last_modified=last_modified)
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}")
        feed = await self._parse(response, body)
        if feed is None:
            raise FetchError("Response is not an RSS or Atom feed")
        return self._result(response, feed)

    async def discover(self, url: str) -> FetchResult:
        """Resolves a website or feed address to a feed: the URL itself, a linked feed, or a common path."""
        url = normalize_url(url)
        host = urlparse(url).netloc
        try:
            response, body = await self._get(url)
        except httpx.HTTPError as exc:
            raise FetchError(f"Couldn't reach {host}: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise FetchError(f"{host} returned HTTP {response.status_code}")
        feed = await self._parse(response, body)
        if feed is not None:
            return self._result(response, feed)

        for candidate in self._candidates(str(response.url), body):
            try:
                response, body = await self._get(candidate)
            except (httpx.HTTPError, FetchError):
                continue
            if response.status_code >= 400:
                continue
            feed = await self._parse(response, body)
            if feed is not None:
                return self._result(response, feed)
        raise FetchError("Couldn't find an RSS or Atom feed at that address")

    # -------------------------------------------------------------- internals

    async def _get(self, url: str, headers: dict | None = None) -> tuple[httpx.Response, bytes]:
        async with self._client.stream("GET", url, headers=headers) as response:
            chunks, size = [], 0
            if response.status_code == 200:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError("Feed is too large")
                    chunks.append(chunk)
            return response, b"".join(chunks)

    @staticmethod
    async def _parse(response: httpx.Response, body: bytes) -> ParsedFeed | None:
        return await asyncio.to_thread(parse_feed, body, str(response.url), response.headers.get("content-type"))

    @staticmethod
    def _result(response: httpx.Response, feed: ParsedFeed) -> FetchResult:
        return FetchResult(
            url=str(response.url), feed=feed,
            etag=response.headers.get("etag"), last_modified=response.headers.get("last-modified"),
        )

    @staticmethod
    def _candidates(page_url: str, body: bytes) -> list[str]:
        parts = urlparse(page_url)
        root = f"{parts.scheme}://{parts.netloc}/"
        linked = find_feed_links(body.decode("utf-8", errors="replace"), page_url)
        guesses = [urljoin(page_url, path) for path in COMMON_FEED_PATHS] + [urljoin(root, path) for path in COMMON_FEED_PATHS]
        seen, candidates = {page_url}, []
        for candidate in linked + guesses:
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
        return candidates
