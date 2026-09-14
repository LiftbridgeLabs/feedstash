import asyncio

import httpx
import pytest

from app.feeds import fetcher as fetcher_module
from app.feeds.fetcher import Fetcher, FetchError, normalize_url

RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>A</title><guid>a</guid></item></channel></rss>'
RSS_HEADERS = {"content-type": "application/rss+xml"}


def run(handler, action):
    """Runs `action(fetcher)` against a mock HTTP server implemented by `handler(request)`."""

    async def main():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            return await action(Fetcher(client))

    return asyncio.run(main())


def test_normalize_url():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("  http://x.example.com/feed ") == "http://x.example.com/feed"
    for bad in ("", "ftp://x.example.com", "https://"):
        with pytest.raises(FetchError):
            normalize_url(bad)


def test_fetch_returns_the_parsed_feed_and_cache_validators():
    def handler(request):
        return httpx.Response(200, content=RSS, headers={**RSS_HEADERS, "etag": '"v2"', "last-modified": "Tue"})

    result = run(handler, lambda f: f.fetch("https://x.example.com/feed"))
    assert not result.not_modified
    assert [e.title for e in result.feed.entries] == ["A"]
    assert (result.etag, result.last_modified) == ('"v2"', "Tue")


def test_fetch_sends_conditional_headers_and_understands_304():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(304)

    result = run(handler, lambda f: f.fetch("https://x.example.com/feed", etag='"v1"', last_modified="Mon"))
    assert result.not_modified
    assert seen["if-none-match"] == '"v1"'
    assert seen["if-modified-since"] == "Mon"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, content=b"<html><body>hi</body></html>", headers={"content-type": "text/html"}), "not an RSS or Atom feed"),
    ],
)
def test_fetch_failures_raise_fetch_error(response, message):
    with pytest.raises(FetchError, match=message):
        run(lambda request: response, lambda f: f.fetch("https://x.example.com/feed"))


def test_network_errors_become_fetch_errors():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(FetchError, match="connection refused"):
        run(handler, lambda f: f.fetch("https://x.example.com/feed"))


def test_oversized_responses_are_rejected(monkeypatch):
    monkeypatch.setattr(fetcher_module, "MAX_BYTES", 10)
    with pytest.raises(FetchError, match="too large"):
        run(lambda request: httpx.Response(200, content=RSS), lambda f: f.fetch("https://x.example.com/feed"))


def test_discover_follows_the_page_feed_link():
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, text='<link rel="alternate" type="application/rss+xml" href="/blog.rss">',
                                  headers={"content-type": "text/html"})
        if request.url.path == "/blog.rss":
            return httpx.Response(200, content=RSS, headers=RSS_HEADERS)
        return httpx.Response(404)

    result = run(handler, lambda f: f.discover("site.example.com"))
    assert result.url == "https://site.example.com/blog.rss"


def test_discover_falls_back_to_common_feed_paths():
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, text="<html>no links</html>", headers={"content-type": "text/html"})
        if request.url.path == "/rss.xml":
            return httpx.Response(200, content=RSS, headers=RSS_HEADERS)
        return httpx.Response(404)

    assert run(handler, lambda f: f.discover("https://site.example.com/")).url == "https://site.example.com/rss.xml"


def test_discover_reports_missing_pages_and_pages_without_feeds():
    with pytest.raises(FetchError, match="returned HTTP 404"):
        run(lambda request: httpx.Response(404), lambda f: f.discover("https://site.example.com/"))

    def no_feed(request):
        if request.url.path == "/":
            return httpx.Response(200, text="<html>nothing</html>", headers={"content-type": "text/html"})
        return httpx.Response(404)

    with pytest.raises(FetchError, match="Couldn't find"):
        run(no_feed, lambda f: f.discover("https://site.example.com/"))
