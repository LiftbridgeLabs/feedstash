import pytest

from app.feeds.reddit import feed_url, name

FEED = "https://www.reddit.com/r/selfhosted/.rss"


@pytest.mark.parametrize("text", [
    "r/selfhosted", "/r/selfhosted/", "  r/selfhosted ", "reddit.com/r/selfhosted", "https://www.reddit.com/r/selfhosted/",
    "https://old.reddit.com/r/selfhosted", "https://www.reddit.com/r/selfhosted/.rss", "m.reddit.com/r/selfhosted/?share=1",
])
def test_a_subreddit_by_name_or_address_becomes_its_feed(text):
    assert feed_url(text) == FEED


@pytest.mark.parametrize("text", [
    "selfhosted", "https://example.com/r/selfhosted", "https://www.reddit.com/r/selfhosted/comments/abc/a_post/",
    "r/x", "r/has spaces", "https://notreddit.com/r/selfhosted", "",
])
def test_anything_else_is_left_alone(text):
    assert feed_url(text) is None


def test_the_name_comes_from_either_form():
    assert name("r/selfhosted") == name("https://old.reddit.com/r/selfhosted/.rss") == "selfhosted"
    assert name("https://example.com/r/selfhosted") is None
