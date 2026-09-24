import pytest

from app.db.models import ItemFilter
from app.db.repositories import feeds as feeds_repo
from app.db.repositories import items as items_repo
from app.db.repositories import smart_lists, stash_folders, stash_rules
from app.errors import Conflict, InvalidInput
from app.feeds import ingest
from app.feeds.parser import ParsedEntry, ParsedFeed


def entry(guid: str, title: str, url: str, summary: str = "") -> ParsedEntry:
    return ParsedEntry(guid=guid, title=title, url=url, author=None, summary=summary, content="", image=None,
                       published_at=1000)


def add_rule(conn, user_id, **fields):
    return stash_rules.create(conn, user_id, now=100, **fields)


def test_rules_match_what_they_say_they_match(conn, user_id):
    item = items_repo.create(conn, user_id, type="link", title="Reef guide for divers", content=None,
                             url="https://www.blog.example.com/reefs", image_name=None, source="web", tags=[], now=100)
    rules = {
        "domain": add_rule(conn, user_id, field="domain", value="blog.example.com", add_tag="a"),
        "subdomain": add_rule(conn, user_id, field="domain", value="example.com", add_tag="b"),
        "other-domain": add_rule(conn, user_id, field="domain", value="example.org", add_tag="c"),
        "url": add_rule(conn, user_id, field="url", value="/reefs", add_tag="d"),
        "title": add_rule(conn, user_id, field="title", value="REEF", add_tag="e"),
        "text": add_rule(conn, user_id, field="text", value="divers", add_tag="f"),
        "type": add_rule(conn, user_id, field="type", value="snippet", add_tag="g"),
    }
    matched = {name for name, rule in rules.items() if stash_rules.matches(rule, item)}
    assert matched == {"domain", "subdomain", "url", "title", "text"}


def test_a_rule_needs_something_to_look_for_and_something_to_do(conn, user_id):
    with pytest.raises(InvalidInput):
        add_rule(conn, user_id, field="domain", value="example.com")  # does nothing
    with pytest.raises(InvalidInput):
        add_rule(conn, user_id, field="domain", value="", add_tag="x")
    with pytest.raises(InvalidInput):
        add_rule(conn, user_id, field="sideways", value="x", add_tag="x")


def test_rules_only_add_and_never_undo(conn, user_id):
    folder = stash_folders.create(conn, user_id, "Reading")
    other = stash_folders.create(conn, user_id, "Elsewhere")
    add_rule(conn, user_id, field="domain", value="example.com", add_tag="Blog", folder_id=folder.id,
             mark_reviewed=True)
    already = items_repo.create(conn, user_id, type="link", title=None, content=None, url="https://example.com/a",
                                image_name=None, source="web", tags=["keep"], now=100, folder_id=other.id)

    assert stash_rules.apply(conn, user_id, already.id, now=200)
    filed = items_repo.get(conn, user_id, already.id)
    assert filed.tags == ["blog", "keep"]  # tags are added (and listed by name), never replaced
    assert filed.folder_id == other.id  # an item already in a folder stays where it is
    assert filed.reviewed

    # Running again changes nothing, and an item the rules don't match is left alone.
    assert not stash_rules.apply(conn, user_id, already.id, now=300)
    elsewhere = items_repo.create(conn, user_id, type="link", title=None, content=None, url="https://other.example/a",
                                  image_name=None, source="web", tags=[], now=100)
    assert not stash_rules.apply(conn, user_id, elsewhere.id, now=300)


def test_new_folders_slot_in_alphabetically_without_disturbing_an_arranged_list(conn, user_id):
    for name in ("Zebra", "Apple", "Mango"):
        stash_folders.create(conn, user_id, name)
    assert [folder.name for folder in stash_folders.list_for_user(conn, user_id)] == ["Apple", "Mango", "Zebra"]

    # Once they're dragged into an order of someone's choosing, a new folder joins without rearranging the rest.
    by_name = {folder.name: folder.id for folder in stash_folders.list_for_user(conn, user_id)}
    stash_folders.reorder(conn, user_id, [by_name["Zebra"], by_name["Apple"], by_name["Mango"]])
    stash_folders.create(conn, user_id, "Banana")
    assert [folder.name for folder in stash_folders.list_for_user(conn, user_id)] == [
        "Banana", "Zebra", "Apple", "Mango"
    ]


def test_smart_lists_need_a_filter_and_a_free_name(conn, user_id):
    folder = stash_folders.create(conn, user_id, "Reading")
    saved = smart_lists.create(conn, user_id, name="Reefs", query="reef", folder_id=folder.id)
    assert (saved.query, saved.folder_id, saved.tag) == ("reef", folder.id, None)
    with pytest.raises(InvalidInput):
        smart_lists.create(conn, user_id, name="Empty")
    with pytest.raises(Conflict):
        smart_lists.create(conn, user_id, name="reefs", query="x")

    assert smart_lists.update(conn, user_id, saved.id, tag="Diving").tag == "diving"
    stash_folders.delete(conn, user_id, folder.id)
    assert smart_lists.list_for_user(conn, user_id) == []


def test_a_feed_can_save_its_new_articles_to_the_stash(conn, user_id):
    feed_id = feeds_repo.create(conn, user_id, url="https://news.example.com/feed", title="News")
    feed = ParsedFeed(title="News", site_url=None, entries=[entry("g1", "First", "https://news.example.com/1")])
    assert ingest.save_entries(conn, feed_id, feed, first_fetch=False, retention_days=90, now=2000) == 1
    assert items_repo.search(conn, user_id, ItemFilter()) == []  # off by default: it stays in the feed

    feeds_repo.set_auto_stash(conn, user_id, feed_id, True)
    add_rule(conn, user_id, field="feed", value=str(feed_id), add_tag="from news")
    second = ParsedFeed(title="News", site_url=None,
                        entries=[entry("g2", "Second", "https://news.example.com/2", summary="A summary")])
    assert ingest.save_entries(conn, feed_id, second, first_fetch=False, retention_days=90, now=2100) == 1

    (item,) = items_repo.search(conn, user_id, ItemFilter())
    assert (item.title, item.source, item.feed_id, item.tags) == ("Second", "feed", feed_id, ["from news"])
    assert item.content == "A summary"
    assert conn.execute("SELECT read_at FROM articles WHERE guid = 'g2'").fetchone()[0] is not None
    assert conn.execute("SELECT read_at FROM articles WHERE guid = 'g1'").fetchone()[0] is None

    # A first fetch is a whole backlog, so it doesn't flood the stash.
    third = ParsedFeed(title="News", site_url=None, entries=[entry("g3", "Third", "https://news.example.com/3")])
    ingest.save_entries(conn, feed_id, third, first_fetch=True, retention_days=90, now=2200)
    assert len(items_repo.search(conn, user_id, ItemFilter())) == 1


def test_running_the_rules_on_everything_goes_in_batches(tmp_path, monkeypatch):
    from app.db import Database
    from app.db.repositories import users
    from app.services import stash as stash_service

    db = Database(tmp_path / "rules.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="sub-ann", email="ann@example.com", name="Ann", picture=None)
        add_rule(conn, user_id, field="domain", value="example.com", add_tag="blog")
        for i in range(450):
            items_repo.create(conn, user_id, type="link", title=None, content=None, url=f"https://example.com/{i}",
                              image_name=None, source="web", tags=[], now=100)

    transactions = []
    real = db.transaction
    monkeypatch.setattr(db, "transaction", lambda: (transactions.append(1), real())[1])
    assert stash_service.apply_rules_to_everything(db, user_id) == 450
    assert len(transactions) == 1 + 3  # the ids, then 200 + 200 + 50
    with db.transaction() as conn:
        assert all(item.tags == ["blog"] for item in items_repo.search(conn, user_id, ItemFilter(limit=1000)))
