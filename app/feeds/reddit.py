"""Subreddits by name. Reddit serves every subreddit as a feed, so "r/selfhosted" (or the subreddit's address) can
be followed like any other, with no Reddit account."""

import re

_NAME = r"[A-Za-z0-9_]{2,21}"
_SHORT = re.compile(rf"^/?r/({_NAME})/?$")
# The subreddit's own page or feed, not a post in it: following a post's address would be a surprise.
_ADDRESS = re.compile(rf"^(?:https?://)?(?:(?:www|old|new|m)\.)?reddit\.com/r/({_NAME})(?:/\.rss)?/?(?:\?.*)?$", re.I)


def feed_url(text: str) -> str | None:
    """The subreddit's feed address for "r/name" or a subreddit's address; None for anything else."""
    text = (text or "").strip()
    match = _SHORT.match(text) or _ADDRESS.match(text)
    return f"https://www.reddit.com/r/{match.group(1)}/.rss" if match else None
