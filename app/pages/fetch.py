"""Fetches a web page and extracts its link preview and a readable copy. Knows nothing about the database."""

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
import trafilatura
from lxml import html as lxml_html
from trafilatura.metadata import extract_metadata

from app.netguard import BlockedAddress, GuardedTransport

# Plenty of sites turn away requests that don't look like they come from a browser, so ask like one.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}
BLOCKED_STATUSES = {401, 403, 451}
MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 200_000
MAX_HTML = 1_000_000


class PageError(Exception):
    """The page couldn't be fetched right now; it may work later. The message is shown to users."""


class PageBlocked(PageError):
    """The site refuses to give FeedStash the page; trying again won't help. Shown to users."""


class NotAWebPage(Exception):
    """The address isn't an HTML page (a PDF, an image, ...), so there's nothing to save. Shown to users."""


@dataclass(frozen=True, slots=True)
class Page:
    url: str  # after redirects
    title: str | None
    description: str | None
    image_url: str | None
    site_name: str | None
    text: str | None  # the article as plain text, for search
    html: str | None  # the article as simple HTML, for reading


def create_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        headers=HEADERS,
        transport=GuardedTransport(limits=httpx.Limits(max_connections=8)),
    )


async def fetch_page(client: httpx.AsyncClient, url: str) -> Page:
    try:
        async with client.stream("GET", url) as response:
            if response.status_code in BLOCKED_STATUSES:
                raise PageBlocked(f"the site blocked FeedStash (HTTP {response.status_code})")
            if response.status_code >= 400:
                raise PageError(f"HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and "html" not in content_type:
                raise NotAWebPage(f"Not a web page ({content_type})")
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise NotAWebPage("The page is too large to save")
                chunks.append(chunk)
            final_url = str(response.url)
    except BlockedAddress as exc:
        raise PageBlocked(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PageError(f"Couldn't reach the page ({exc.__class__.__name__})") from exc
    return await asyncio.to_thread(extract, b"".join(chunks), final_url)


def extract(body: bytes | str, url: str) -> Page:
    """The preview (title, description, image, site name) and readable copy of an HTML document."""
    meta = extract_metadata(trafilatura.load_html(body), default_url=url)
    options = {"url": url, "include_comments": False, "include_tables": True}
    text = trafilatura.extract(body, **options)
    readable = trafilatura.extract(
        body, output_format="html", include_images=True, include_links=True, include_formatting=True, **options
    )
    return Page(
        url=url,
        title=_clip(getattr(meta, "title", None), 500),
        description=_clip(getattr(meta, "description", None), 1000),
        image_url=_web_url(url, getattr(meta, "image", None)),
        site_name=_clip(getattr(meta, "sitename", None), 200),
        text=(text or "")[:MAX_TEXT] or None,
        html=_readable_html(readable, url),
    )


def _clip(value: str | None, limit: int) -> str | None:
    value = " ".join((value or "").split())
    return value[:limit] or None


def _web_url(base: str, value: str | None) -> str | None:
    if not value:
        return None
    absolute = urljoin(base, value.strip())
    return absolute if absolute.lower().startswith(("http://", "https://")) else None


def _readable_html(document: str | None, base_url: str) -> str | None:
    """trafilatura's HTML with images as <img> and every address absolute. The browser sanitizes it again."""
    if not document:
        return None
    root = lxml_html.fromstring(document)
    body = root.find("body") if root.tag == "html" else root
    if body is None:
        body = root
    for element in list(body.iter("graphic")):
        element.tag = "img"
    for element in body.iter("img"):
        if element.get("src"):
            element.set("src", urljoin(base_url, element.get("src")))
    for element in body.iter("a"):
        if element.get("href"):
            element.set("href", urljoin(base_url, element.get("href")))
    html = (body.text or "") + "".join(lxml_html.tostring(child, encoding="unicode") for child in body)
    return html.strip()[:MAX_HTML] or None
