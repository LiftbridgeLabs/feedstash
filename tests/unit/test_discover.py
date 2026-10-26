"""The Discover catalog: well-formed, so a typo can't ship."""

from urllib.parse import urlparse

from app.feeds import discover


def test_every_pack_and_feed_is_complete_and_https():
    packs = discover.packs()
    assert len(packs) >= 5
    assert len({pack.id for pack in packs}) == len(packs)
    urls = [feed.url for pack in packs for feed in pack.feeds]
    assert len(set(urls)) == len(urls)
    for pack in packs:
        assert pack.name and pack.description and len(pack.feeds) >= 2
        for feed in pack.feeds:
            assert feed.title and feed.about and feed.cadence
            assert urlparse(feed.url).scheme == "https" and urlparse(feed.site).scheme == "https"
