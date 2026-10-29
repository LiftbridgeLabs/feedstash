"""Downloads feeds over HTTP. Knows nothing about the database."""

import asyncio
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import httpx

from app import clock
from app.feeds.parser import ParsedFeed, find_feed_links, parse_feed
from app.netguard import BlockedAddress, GuardedTransport

# An honest name, not a browser's: sites behind bot protection (Cloudflare's, for one) challenge anything that says
# "Mozilla" without being a real browser, and let a plainly named feed reader through.
USER_AGENT = "FeedStash (+https://github.com/LiftbridgeLabs/feedstash)"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
MAX_BYTES = 15 * 1024 * 1024
# The client's timeout is per read, so a server trickling a byte at a time could hold a fetch (and the refresh round
# waiting on it) for hours. This bounds the whole download.
DEADLINE_SECONDS = 90
COMMON_FEED_PATHS = ("feed", "rss", "feed.xml", "rss.xml", "atom.xml", "index.xml")


class FetchError(Exception):
    """A feed couldn't be fetched. The message is meant to be shown to users; `status` is the site's HTTP status,
    when it answered with an error."""

    def __init__(self, message: str = "", status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimited(FetchError):
    """The site said too many requests (HTTP 429). `retry_after` is how many seconds it asked for, if it said."""

    def __init__(self, message: str, retry_after: int | None):
        super().__init__(message)
        self.retry_after = retry_after


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
        transport=GuardedTransport(limits=httpx.Limits(max_connections=max_connections)),
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
            response, body = await self._secure_if_refused(url, *await self._get(url, headers), headers)
        except httpx.HTTPError as exc:
            raise FetchError(str(exc) or exc.__class__.__name__) from exc
        if response.status_code == 304:
            return FetchResult(url=str(response.url), feed=None, etag=etag, last_modified=last_modified)
        if response.status_code >= 400:
            raise _http_error(response)
        feed = await self._parse(response, body)
        if feed is None:
            raise FetchError("Response is not an RSS or Atom feed")
        return self._result(response, feed)

    async def discover(self, url: str) -> FetchResult:
        """Resolves a website or feed address to a feed: the URL itself, a linked feed, or a common path."""
        url = normalize_url(url)
        host = urlparse(url).netloc
        try:
            response, body = await self._secure_if_refused(url, *await self._get(url))
        except BlockedAddress as exc:
            raise FetchError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"Couldn't reach {host}: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise _http_error(response)
        feed = await self._parse(response, body)
        if feed is not None:
            return self._result(response, feed)

        for candidate in self._candidates(str(response.url), body):
            try:
                response, body = await self._secure_if_refused(candidate, *await self._get(candidate))
            except (httpx.HTTPError, FetchError):
                continue
            if response.status_code >= 400:
                continue
            feed = await self._parse(response, body)
            if feed is not None:
                return self._result(response, feed)
        raise FetchError("Couldn't find an RSS or Atom feed at that address")

    # -------------------------------------------------------------- internals

    async def _secure_if_refused(
        self, url: str, response: httpx.Response, body: bytes, headers: dict | None = None,
    ) -> tuple[httpx.Response, bytes]:
        """When an http:// address is refused, the https:// one, if that works. Some sites refuse plain http outright
        instead of redirecting (PhoneArena's Cloudflare answers 403), and old feed addresses, like ones in a Feedly
        export, are often still http. The result's URL is the https one, so the caller can keep it."""
        # The address that refused, after any redirects: that's the one to try on https.
        secure = secure_url(str(response.url)) or secure_url(url)
        # Not for "too many requests": asking again at once would dodge the rest a site asked for.
        if response.status_code < 400 or response.status_code == 429 or secure is None:
            return response, body
        try:
            secured, secured_body = await self._get(secure, headers)
        except (httpx.HTTPError, FetchError):
            return response, body
        # https saying "too many requests" counts: its Retry-After starts the rest.
        return (secured, secured_body) if secured.status_code < 400 or secured.status_code == 429 else (response, body)

    async def _get(self, url: str, headers: dict | None = None) -> tuple[httpx.Response, bytes]:
        try:
            async with asyncio.timeout(DEADLINE_SECONDS), self._client.stream("GET", url, headers=headers) as response:
                chunks, size = [], 0
                if response.is_success:  # 203 from a caching proxy has a feed in it too
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise FetchError("Feed is too large")
                        chunks.append(chunk)
                return response, b"".join(chunks)
        except TimeoutError:
            raise FetchError(f"The feed took more than {DEADLINE_SECONDS} seconds to download") from None

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


def secure_url(url: str) -> str | None:
    """The https:// version of an http:// address, or None for anything else."""
    return "https://" + url[7:] if url[:7].lower() == "http://" else None


def _http_error(response: httpx.Response) -> FetchError:
    host = urlparse(str(response.url)).netloc
    code = response.status_code
    if code == 429:
        return RateLimited(
            f"{host} asked FeedStash to slow down (HTTP 429). It will try again later.",
            _retry_after(response.headers.get("retry-after")),
        )
    if _is_bot_check(response):
        return FetchError(
            f"{host} only lets web browsers in: it checks every visitor for bots, and feed readers can't pass "
            f"(HTTP {code}). Some sites will let their feed through if you ask them."
        )
    if code == 403:
        return FetchError(f"{host} turned FeedStash away (HTTP 403). Some sites block feed readers.")
    return FetchError(f"{host} returned HTTP {code}", code)


def _is_bot_check(response: httpx.Response) -> bool:
    """A refusal from bot protection that only lets browsers in, told by the header its challenge carries:
    Cloudflare's challenge, Anexia's proof of work (netcup), DataDome, AWS WAF's challenge or captcha."""
    headers = response.headers
    return (
        headers.get("cf-mitigated", "").lower() == "challenge"
        or "x-anx-pow" in headers
        or "x-datadome" in headers
        or headers.get("x-amzn-waf-action", "").lower() in ("challenge", "captcha")
    )


def _retry_after(value: str | None) -> int | None:
    """Retry-After is either seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return None
    return max(0, int(moment.timestamp()) - clock.now())
