import pytest

from app.db.models import ItemFilter, ItemLink
from app.db.repositories import items, tokens, users
from app.errors import InvalidInput, NotFound
from app.services.stash import parse_links


def add(conn, user_id, *, now=1000, **fields):
    values = {"type": "link", "title": None, "content": None, "url": "https://example.com", "image_name": None,
              "source": "test", "tags": [], **fields}
    return items.create(conn, user_id, now=now, **values)


def test_tags_are_normalized():
    assert items.normalize_tags([" Dev ", "#dev", "", "Two   Words", "x" * 80]) == ["dev", "two words", "x" * 50]


def test_search_combines_filters_and_matches_wildcards_literally(conn, user_id):
    add(conn, user_id, title="50% off", tags=["deals"], now=1)
    add(conn, user_id, type="snippet", content="plain", url=None, tags=["deals"], now=2)
    archived = add(conn, user_id, title="old deal", tags=["deals"], now=3)
    items.update(conn, user_id, archived.id, now=4, archived=True)

    assert [i.title for i in items.search(conn, user_id, ItemFilter(query="50%"))] == ["50% off"]
    assert items.search(conn, user_id, ItemFilter(query="5_%")) == []
    assert [i.type for i in items.search(conn, user_id, ItemFilter(tag="DEALS"))] == ["snippet", "link"]
    assert [i.type for i in items.search(conn, user_id, ItemFilter(tag="deals", type="link"))] == ["link"]
    assert [i.title for i in items.search(conn, user_id, ItemFilter(archived=True))] == ["old deal"]
    assert [i.type for i in items.search(conn, user_id, ItemFilter(limit=1, offset=1))] == ["link"]


def test_update_keeps_the_first_review_time_and_can_clear_fields(conn, user_id):
    item = add(conn, user_id, title="Title")
    items.update(conn, user_id, item.id, now=2000, reviewed=True)
    items.update(conn, user_id, item.id, now=3000, reviewed=True)
    assert conn.execute("SELECT reviewed_at FROM items WHERE id = ?", (item.id,)).fetchone()[0] == 2000

    cleared = items.update(conn, user_id, item.id, now=4000, title=None)
    assert cleared.title is None and cleared.reviewed and cleared.updated_at == 4000
    assert not items.update(conn, user_id, item.id, now=5000, reviewed=False).reviewed


def test_unused_tags_are_removed(conn, user_id):
    item = add(conn, user_id, tags=["keep", "drop"])
    add(conn, user_id, tags=["keep"])
    items.update(conn, user_id, item.id, now=2000, tags=["keep"])
    assert [t.name for t in items.tag_counts(conn, user_id)] == ["keep"]
    items.delete(conn, user_id, item.id)
    assert [(t.name, t.count) for t in items.tag_counts(conn, user_id)] == [("keep", 1)]


def test_links_keep_their_order_and_url_mirrors_the_first(conn, user_id):
    a, b = ItemLink("https://a.example.com", "A"), ItemLink("https://b.example.com")
    item = add(conn, user_id, url="https://b.example.com", links=[a, b])
    assert item.url == "https://a.example.com"  # a url already among the links isn't moved
    assert [(link.url, link.label) for link in item.links] == [("https://a.example.com", "A"), ("https://b.example.com", None)]
    folded = add(conn, user_id, url="https://new.example.com", links=[a])
    assert [link.url for link in folded.links] == ["https://new.example.com", "https://a.example.com"]

    assert items.update(conn, user_id, item.id, now=2, url="https://a.example.com").links[0].label == "A"
    swapped = items.update(conn, user_id, item.id, now=3, url="https://c.example.com")
    assert [link.url for link in swapped.links] == ["https://c.example.com", "https://b.example.com"]
    cleared = items.update(conn, user_id, item.id, now=4, url=None)
    assert cleared.url == "https://b.example.com" and len(cleared.links) == 1

    items.delete(conn, user_id, item.id)
    assert conn.execute("SELECT COUNT(*) FROM item_links WHERE item_id = ?", (item.id,)).fetchone()[0] == 0


def test_links_are_parsed_from_every_shape_clients_send():
    a, b = ItemLink("https://a.example.com"), ItemLink("https://b.example.com")
    assert parse_links(None) is None
    assert parse_links("  ") == []
    assert parse_links('[{"url": " https://a.example.com ", "label": " A "}, "https://b.example.com", {"label": "x"}]') == [
        ItemLink("https://a.example.com", "A"), b,
    ]
    assert parse_links("https://a.example.com\r\n\nhttps://b.example.com") == [a, b]
    assert parse_links({"url": "https://a.example.com"}) == [a]
    with pytest.raises(InvalidInput):
        parse_links(["https://x.example.com"] * 101)


def test_other_users_items_are_invisible(conn, user_id):
    other = users.upsert(conn, sub="sub-bob", email="bob@example.com", name=None, picture=None)
    theirs = add(conn, other, tags=["private"])
    assert items.search(conn, user_id, ItemFilter()) == []
    assert items.tag_counts(conn, user_id) == []
    with pytest.raises(NotFound):
        items.get(conn, user_id, theirs.id)
    with pytest.raises(NotFound):
        items.update(conn, user_id, theirs.id, now=1, reviewed=True)
    with pytest.raises(NotFound):
        items.delete(conn, user_id, theirs.id)
    with pytest.raises(InvalidInput):
        add(conn, user_id, type="video")


def test_tokens_are_stored_hashed_and_authenticate(conn, user_id):
    token, secret = tokens.create(conn, user_id, " Phone ", now=100)
    assert token.client_name == "Phone" and token.hint == secret[-4:]
    stored = conn.execute("SELECT token_hash FROM api_tokens").fetchone()[0]
    assert stored == tokens.hash_token(secret) and secret not in stored

    match = tokens.authenticate(conn, secret, now=200)
    assert (match.user_id, match.client_name) == (user_id, "Phone")
    assert tokens.authenticate(conn, "wrong", now=200) is None

    last_used = lambda: tokens.list_for_user(conn, user_id)[0].last_used_at  # noqa: E731
    assert last_used() == 200
    tokens.authenticate(conn, secret, now=230)
    assert last_used() == 200  # not rewritten within a minute
    tokens.authenticate(conn, secret, now=300)
    assert last_used() == 300

    tokens.delete(conn, user_id, token.id)
    assert tokens.authenticate(conn, secret, now=400) is None
    with pytest.raises(NotFound):
        tokens.delete(conn, user_id, token.id)
