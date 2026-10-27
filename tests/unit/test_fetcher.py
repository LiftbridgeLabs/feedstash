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


def test_feeds_are_asked_for_by_name_and_refusals_say_so():
    agent = asyncio.run(_agent())
    assert agent.startswith("FeedStash") and "Mozilla" not in agent
    with pytest.raises(FetchError, match="turned FeedStash away"):
        run(lambda request: httpx.Response(403), lambda f: f.fetch("https://x.example.com/feed"))


def test_a_bot_check_says_the_site_only_lets_browsers_in():
    challenges = [
        {"cf-mitigated": "challenge"},  # Cloudflare
        {"x-anx-pow": "true"},  # Anexia's proof of work (netcup)
        {"x-datadome": "protected"},
        {"x-amzn-waf-action": "captcha"},
    ]
    for headers in challenges:
        refuse = lambda request, headers=headers: httpx.Response(403, headers=headers, text="<html>checking</html>")
        with pytest.raises(FetchError, match="only lets web browsers in"):
            run(refuse, lambda f: f.fetch("https://x.example.com/feed"))
        # Following it says so too, not just "returned HTTP 403".
        with pytest.raises(FetchError, match="only lets web browsers in"):
            run(refuse, lambda f: f.discover("https://x.example.com/"))
    # A plain refusal keeps its own wording.
    with pytest.raises(FetchError, match="turned FeedStash away"):
        run(lambda request: httpx.Response(403), lambda f: f.discover("https://x.example.com/"))


async def _agent() -> str:
    async with fetcher_module.create_client() as client:
        return client.headers["user-agent"]


def test_an_http_feed_that_is_refused_is_tried_on_https():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.scheme == "http":
            return httpx.Response(403)  # Cloudflare refusing plain http, no redirect
        return httpx.Response(200, content=RSS, headers=RSS_HEADERS)

    result = run(handler, lambda f: f.fetch("http://x.example.com/feed/news"))
    assert result.url == "https://x.example.com/feed/news" and [e.title for e in result.feed.entries] == ["A"]
    found = run(handler, lambda f: f.discover("http://x.example.com/feed/news"))
    assert found.url == "https://x.example.com/feed/news"
    # https that's refused too keeps the original error.
    with pytest.raises(FetchError, match="turned FeedStash away"):
        run(lambda request: httpx.Response(403), lambda f: f.fetch("http://x.example.com/feed"))


def test_a_rate_limited_http_feed_isnt_asked_again_on_https():
    seen = []

    def handler(request):
        seen.append(request.url.scheme)
        return httpx.Response(429) if request.url.scheme == "http" else httpx.Response(200, content=RSS, headers=RSS_HEADERS)

    with pytest.raises(FetchError, match="slow down"):
        run(handler, lambda f: f.fetch("http://x.example.com/feed"))
    assert seen == ["http"]


def test_feeds_a_page_links_to_get_the_https_fallback_too():
    page = b'<html><head><link rel="alternate" type="application/rss+xml" href="http://x.example.com/feed.xml"></head></html>'

    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, content=page, headers={"content-type": "text/html"})
        if request.url.scheme == "http":
            return httpx.Response(403)
        return httpx.Response(200, content=RSS, headers=RSS_HEADERS) if request.url.path == "/feed.xml" else httpx.Response(404)

    assert run(handler, lambda f: f.discover("https://x.example.com/")).url == "https://x.example.com/feed.xml"


def test_the_https_fallback_follows_redirects_and_keeps_a_rate_limit():
    def redirected(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "http://x.example.com/new"})
        if request.url.scheme == "http":
            return httpx.Response(403)
        return httpx.Response(200, content=RSS, headers=RSS_HEADERS) if request.url.path == "/new" else httpx.Response(404)

    assert run(redirected, lambda f: f.fetch("http://x.example.com/old")).url == "https://x.example.com/new"

    def busy_on_https(request):
        if request.url.scheme == "http":
            return httpx.Response(403)
        return httpx.Response(429, headers={"retry-after": "600"})

    with pytest.raises(fetcher_module.RateLimited) as caught:
        run(busy_on_https, lambda f: f.fetch("http://x.example.com/feed"))
    assert caught.value.retry_after == 600
