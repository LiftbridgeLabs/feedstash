import calendar

from app.feeds.parser import MAX_ENTRIES, find_feed_links, parse_feed

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title> My   Blog </title><link>https://blog.example.com/</link>
<item><title><![CDATA[Hello &amp; <b>welcome</b>]]></title><link>https://blog.example.com/posts/1</link><guid>post-1</guid>
<pubDate>Mon, 14 Sep 2026 10:00:00 GMT</pubDate>
<description><![CDATA[<p>Hi <script>alert(1)</script><img src="/img/a.png" onerror="steal()"> there</p>]]></description></item>
<item><title>No date</title><description>Plain words</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Site</title>
<link href="https://site.example.com/"/>
<entry><title>Plain</title><id>urn:entry:1</id><link href="/p/1"/><updated>2026-09-14T10:00:00Z</updated>
<content type="text">line one
line two &lt;b&gt;</content></entry></feed>"""

LATER = 2_000_000_000  # a "now" after every date in the samples


def test_rss_items_are_parsed_sanitized_and_enriched():
    feed = parse_feed(RSS, "https://blog.example.com/feed.xml", "application/rss+xml", now=LATER)
    assert feed.title == "My Blog"
    assert feed.site_url == "https://blog.example.com/"
    first, second = feed.entries

    # RSS guids are permalinks by default, so feedparser resolves them against the feed URL.
    assert first.guid == "https://blog.example.com/post-1"
    assert first.title == "Hello & welcome"
    assert first.url == "https://blog.example.com/posts/1"
    assert first.published_at == calendar.timegm((2026, 9, 14, 10, 0, 0))
    assert "<script" not in first.content and "onerror" not in first.content
    assert first.image == "https://blog.example.com/img/a.png"
    assert first.summary == "Hi there"

    assert second.published_at is None
    assert len(second.guid) == 40  # generated from the content when the feed has no id or link
    assert second.summary == "Plain words"


def test_future_dates_are_clamped_to_now():
    feed = parse_feed(RSS, "https://blog.example.com/feed.xml", now=1000)
    assert feed.entries[0].published_at == 1000


def test_atom_relative_links_resolve_and_plain_text_content_is_escaped():
    entry = parse_feed(ATOM, "https://site.example.com/feed", "application/atom+xml", now=LATER).entries[0]
    assert entry.url == "https://site.example.com/p/1"
    assert "line one<br>line two &lt;b&gt;" in entry.content


def test_documents_that_are_not_feeds_return_none():
    assert parse_feed(b"<html><body><p>hi</p></body></html>", "https://site.example.com/", "text/html") is None


def test_feed_title_falls_back_to_the_host():
    rss = b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>x</title><guid>1</guid></item></channel></rss>'
    assert parse_feed(rss, "https://news.example.org/rss").title == "news.example.org"


def test_entry_count_is_capped():
    items = "".join(f"<item><title>{i}</title><guid>{i}</guid></item>" for i in range(MAX_ENTRIES + 50))
    rss = f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'.encode()
    assert len(parse_feed(rss, "https://x.example.com/").entries) == MAX_ENTRIES


def test_find_feed_links_returns_absolute_feed_urls_only():
    page = """<head>
      <link rel="alternate" type="application/rss+xml" href="/feed">
      <link rel="stylesheet" href="site.css">
      <link rel="Alternate" type="application/atom+xml" href="https://other.example.com/atom">
      <link rel="alternate" type="text/html" href="/en">
    </head>"""
    assert find_feed_links(page, "https://site.example.com/blog/") == [
        "https://site.example.com/feed",
        "https://other.example.com/atom",
    ]
