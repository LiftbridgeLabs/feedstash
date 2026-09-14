"""Writes deterministic test feeds into a directory that the tests serve over HTTP.

File names deliberately avoid the paths feed discovery guesses (/feed, /atom.xml, ...), so a page
without a feed really has no feed to find.
"""

import time
from email.utils import formatdate
from pathlib import Path

# Ages (in hours) of the 15 items in tech.xml; the "older than" tests depend on these.
TECH_AGES_HOURS = [0.2, 1, 3, 6, 11, 13, 20, 23, 25, 30, 47, 60, 100, 170, 200]
ATOM_ENTRY_COUNT = 60  # one every 30 minutes


def write_feeds(root: Path, base_url: str) -> None:
    now = time.time()

    items = "".join(
        f"""<item><title>Tech story {i} ({hours}h old)</title><link>https://example.com/tech/{i}</link>
<guid>tech-{i}</guid><pubDate>{formatdate(now - hours * 3600)}</pubDate>
<description><![CDATA[<p>Paragraph for story {i}. <img src="https://example.com/img/{i}.jpg">
<a href="javascript:alert(1)">bad link</a> <script>alert(1)</script><b onclick="alert(1)">bold</b></p>]]></description></item>"""
        for i, hours in enumerate(TECH_AGES_HOURS)
    )
    (root / "tech.xml").write_text(
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>Test Tech</title>'
        f"<link>https://example.com/</link>{items}</channel></rss>",
        encoding="utf-8",
    )

    entries = "".join(
        f"""<entry><title>Atom post {i}</title><id>atom-{i}</id><link href="/posts/{i}"/>
<updated>{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 1800))}</updated>
<content type="html">&lt;p&gt;Atom body {i}&lt;/p&gt;</content></entry>"""
        for i in range(ATOM_ENTRY_COUNT)
    )
    (root / "posts.atom").write_text(
        f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f'<title>Atom Blog</title><link href="{base_url}/"/>{entries}</feed>',
        encoding="utf-8",
    )

    # A web page that only links to its feed, for discovery.
    (root / "site.html").write_text(
        '<html><head><link rel="alternate" type="application/atom+xml" href="posts.atom"></head><body>Blog</body></html>',
        encoding="utf-8",
    )
    # A web page with no feed at all.
    (root / "plain.html").write_text("<html><head><title>No feed</title></head><body>Hi</body></html>", encoding="utf-8")

    (root / "subs.opml").write_text(
        f"""<?xml version="1.0"?><opml version="1.0"><head><title>Feedly</title></head><body>
<outline text="News" title="News"><outline type="rss" text="Atom Blog" xmlUrl="{base_url}/posts.atom" htmlUrl="{base_url}/"/></outline>
<outline type="rss" text="Loose" xmlUrl="{base_url}/missing.xml"/>
</body></opml>""",
        encoding="utf-8",
    )
