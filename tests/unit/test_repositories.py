import pytest

from app.db.models import NewArticle, Scope
from app.db.repositories import articles, feeds, folders, users
from app.db.repositories._common import ordered_ids
from app.errors import Conflict, InvalidInput, NotFound


def new_articles(count: int, *, first_published: int) -> list[NewArticle]:
    return [
        NewArticle(guid=f"g{i}", title=f"T{i}", url=None, author=None, summary="", content="", image=None,
                   published_at=first_published + i)
        for i in range(count)
    ]


def test_ordered_ids_puts_requested_first_and_keeps_the_rest():
    assert ordered_ids([1, 2, 3, 4], [3, 1], {1, 2, 3, 4}) == [3, 1, 2, 4]
    with pytest.raises(InvalidInput):
        ordered_ids([1, 2], [1, 1], {1, 2})
    with pytest.raises(InvalidInput):
        ordered_ids([1, 2], [9], {1, 2})


def test_upsert_updates_an_existing_user(conn, user_id):
    again = users.upsert(conn, sub="sub-ann", email="new@example.com", name="Ann B", picture="https://p.example.com/a.png")
    assert again == user_id
    assert users.get(conn, user_id).email == "new@example.com"
    assert users.get(conn, 999) is None


def test_folder_names_are_cleaned_and_unique(conn, user_id):
    folder = folders.create(conn, user_id, "  News   Stuff ")
    assert (folder.name, folder.position) == ("News Stuff", 0)
    assert folders.create(conn, user_id, "Second").position == 1
    with pytest.raises(Conflict):
        folders.create(conn, user_id, "News Stuff")
    with pytest.raises(InvalidInput):
        folders.create(conn, user_id, "   ")
    assert folders.get_or_create(conn, user_id, "News Stuff").id == folder.id
    with pytest.raises(NotFound):
        folders.get(conn, user_id, 999)


def test_users_cannot_touch_each_others_data(conn, user_id):
    other = users.upsert(conn, sub="sub-bob", email="bob@example.com", name=None, picture=None)
    their_folder = folders.create(conn, other, "Theirs")
    their_feed = feeds.create(conn, other, url="https://x.example.com/feed", title="X")

    assert folders.list_for_user(conn, user_id) == []
    assert feeds.list_for_user(conn, user_id) == []
    with pytest.raises(NotFound):
        folders.rename(conn, user_id, their_folder.id, "Mine")
    with pytest.raises(NotFound):
        feeds.get(conn, user_id, their_feed)
    with pytest.raises(NotFound):
        feeds.create(conn, user_id, url="https://y.example.com/feed", title="Y", folder_id=their_folder.id)
    with pytest.raises(InvalidInput):
        feeds.reorder(conn, user_id, None, [their_feed])


def test_moving_a_feed_appends_it_to_the_target_folder(conn, user_id):
    folder = folders.create(conn, user_id, "A")
    first = feeds.create(conn, user_id, url="https://1.example.com/", title="One", folder_id=folder.id)
    second = feeds.create(conn, user_id, url="https://2.example.com/", title="Two")
    feeds.move(conn, user_id, second, folder.id)
    assert [f.id for f in feeds.list_for_user(conn, user_id) if f.folder_id == folder.id] == [first, second]


def test_deleting_a_folder_keeps_its_feeds_in_order(conn, user_id):
    loose = feeds.create(conn, user_id, url="https://0.example.com/", title="Loose")
    folder = folders.create(conn, user_id, "A")
    b = feeds.create(conn, user_id, url="https://b.example.com/", title="B", folder_id=folder.id)
    a = feeds.create(conn, user_id, url="https://a.example.com/", title="A", folder_id=folder.id)
    folders.delete(conn, user_id, folder.id, unfollow_feeds=False)
    assert [f.id for f in feeds.list_for_user(conn, user_id)] == [loose, b, a]


def test_article_pages_follow_the_cursor_and_validate_input(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    articles.insert_new(conn, feed_id, new_articles(5, first_published=1000), fetched_at=2000)
    scope = Scope("feed", feed_id)

    first = articles.page(conn, user_id, scope, limit=2)
    assert [a.title for a in first.articles] == ["T4", "T3"]
    second = articles.page(conn, user_id, scope, limit=2, cursor=first.next_cursor, max_id=first.max_id)
    assert [a.title for a in second.articles] == ["T2", "T1"]

    with pytest.raises(InvalidInput):
        articles.page(conn, user_id, Scope("folder"))
    with pytest.raises(InvalidInput):
        articles.page(conn, user_id, Scope("all"), cursor="nope")


def test_inserting_the_same_guid_twice_adds_nothing(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    assert articles.insert_new(conn, feed_id, new_articles(3, first_published=1), fetched_at=10) == 3
    assert articles.insert_new(conn, feed_id, new_articles(3, first_published=1), fetched_at=20) == 0


def test_mark_scope_read_and_undo(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    articles.insert_new(conn, feed_id, new_articles(4, first_published=100), fetched_at=200)
    assert articles.mark_scope_read(conn, user_id, Scope("all"), batch=500, published_before=102) == 2
    assert articles.undo_mark_scope_read(conn, user_id, Scope("all"), batch=500) == 2
    assert articles.count_new(conn, user_id, Scope("all"), since_id=0, unread_only=True) == 4


def test_purge_keeps_starred_articles_and_the_newest_per_feed(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    articles.insert_new(conn, feed_id, new_articles(10, first_published=1), fetched_at=50)
    oldest = conn.execute("SELECT id FROM articles WHERE guid = 'g0'").fetchone()[0]
    articles.set_starred(conn, user_id, oldest, starred=True, now=60)

    assert articles.purge(conn, published_before=100, keep_per_feed=3) == 6
    assert {row["title"] for row in conn.execute("SELECT title FROM articles")} == {"T9", "T8", "T7", "T0"}
