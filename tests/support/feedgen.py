"""Writes deterministic test feeds into a directory that the tests serve over HTTP.

File names deliberately avoid the paths feed discovery guesses (/feed, /atom.xml, ...), so a page
without a feed really has no feed to find.
"""

import time
from email.utils import formatdate
from pathlib import Path

from support.images import PNG

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

    # An article to save to the stash: a preview in its meta tags, a readable body between navigation and a footer.
    (root / "article.html").write_text(
        """<!doctype html><html><head>
<title>Reef guide | Dive Mag</title>
<meta property="og:title" content="The best reefs for beginner divers">
<meta property="og:description" content="Calm water, shallow walls and lots of fish.">
<meta property="og:image" content="/img/reef.png">
<meta property="og:site_name" content="Dive Mag">
<script>window.tracker = 1</script>
</head><body>
<nav><a href="/">Home</a> <a href="/shop">Shop</a></nav>
<article>
<h1>The best reefs for beginner divers</h1>
<p>Cozumel drift dives are gentle enough for a first trip, with visibility that often tops thirty metres.</p>
<p>Bonaire lets you <a href="/shore">dive from the shore</a> almost anywhere along the coast, and its marine park
protects the reefs around the whole island.</p>
<img src="/img/turtle.png" alt="A turtle">
<p>The Red Sea's northern reefs are close to resorts and busy with nudibranchs all year round.</p>
</article>
<footer>Copyright Dive Mag. Subscribe to our newsletter.</footer>
</body></html>""",
        encoding="utf-8",
    )
    # A feed that only sends a one-line summary; its articles' pages have the whole story.
    (root / "longreads.xml").write_text(
        f'''<?xml version="1.0"?><rss version="2.0"><channel><title>Long Reads</title><link>{base_url}/</link>
<item><title>Reef guide</title><link>{base_url}/article.html</link><guid>reef</guid>
<pubDate>{formatdate(now - 3600)}</pubDate><description>Where to dive first.</description></item>
<item><title>Tide tables</title><link>{base_url}/tides.html</link><guid>tides</guid>
<pubDate>{formatdate(now - 7200)}</pubDate><description>Reading the tides.</description></item>
<item><title>Missing page</title><link>{base_url}/gone.html</link><guid>gone</guid>
<pubDate>{formatdate(now - 10800)}</pubDate><description>This one has no page.</description></item>
</channel></rss>''',
        encoding="utf-8",
    )
    (root / "tides.html").write_text(
        """<!doctype html><html><head><title>Tide tables</title></head><body><nav>Menu</nav><article>
<h1>Reading tide tables</h1>
<p>Slack water at the reef entrance lasts about forty minutes, which is when the current stops pulling divers along.</p>
<p>Spring tides bring the strongest currents twice a month, around the new and full moon.</p>
</article><footer>Footer</footer></body></html>""",
        encoding="utf-8",
    )
    (root / "img").mkdir(exist_ok=True)
    (root / "img" / "reef.png").write_bytes(PNG)  # decodable, so the browser keeps the thumbnail
    (root / "img" / "turtle.png").write_bytes(PNG)
    (root / "notes.txt").write_text("Plain text, not a web page.", encoding="utf-8")

    (root / "subs.opml").write_text(
        f"""<?xml version="1.0"?><opml version="1.0"><head><title>Feedly</title></head><body>
<outline text="News" title="News"><outline type="rss" text="Atom Blog" xmlUrl="{base_url}/posts.atom" htmlUrl="{base_url}/"/></outline>
<outline type="rss" text="Loose" xmlUrl="{base_url}/missing.xml"/>
</body></opml>""",
        encoding="utf-8",
    )
