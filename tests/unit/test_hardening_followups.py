"""Follow-ups from the code review: small inputs that used to crash, secrets that must stay out of logs, and the
queries and writes that didn't scale."""

import asyncio

import httpx

from app.db.database import Database
from app.db.models import NewArticle, Scope
from app.db.repositories import articles, feeds, items, search, users
from app.feeds.fetcher import Fetcher
from app.mail.imap import MailboxConfig
from app.opml import parse_opml
from app.services import bookmarks


def test_deeply_nested_opml_is_read_instead_of_crashing():
    depth = 3000
    nested = "".join('<outline text="level">' for _ in range(depth))
    nested += '<outline text="Feed" xmlUrl="https://example.com/feed.xml"/>' + "</outline>" * depth
    data = f'<?xml version="1.0"?><opml version="2.0"><body>{nested}</body></opml>'.encode()
    assert parse_opml(data) == [("level", "https://example.com/feed.xml", "Feed")]


def test_opml_keeps_folders_and_order():
    data = b"""<opml version="2.0"><body>
      <outline text="Tech"><outline text="A" xmlUrl="https://a.example/feed"/><outline text="B" xmlUrl="https://b.example/feed"/></outline>
      <outline text="Loose" xmlUrl="https://c.example/feed"/>
    </body></opml>"""
    assert parse_opml(data) == [
        ("Tech", "https://a.example/feed", "A"), ("Tech", "https://b.example/feed", "B"), (None, "https://c.example/feed", "Loose"),
    ]


def test_a_mailbox_password_never_shows_in_a_repr():
    fields = {name: "x" for name in MailboxConfig.__dataclass_fields__}
    fields.update(password="hunter2-secret", port=993) if "port" in fields else fields.update(password="hunter2-secret")
    config = MailboxConfig(**fields)
    assert "hunter2-secret" not in repr(config)


def _article(guid, published_at, title="Story"):
    return NewArticle(guid=guid, title=title, url=None, author=None, summary="", content="", image=None,
                      published_at=published_at)


def _pages(conn, user_id, order):
    seen, cursor = [], None
    while True:
        result = articles.page(conn, user_id, Scope("all"), order=order, cursor=cursor, limit=7)
        seen += [article.id for article in result.articles]
        if not (cursor := result.next_cursor):
            return seen


def _all_unread_plan(conn, user_id):
    statements = []
    conn.set_trace_callback(statements.append)
    articles.page(conn, user_id, Scope("all"), limit=7)
    conn.set_trace_callback(None)
    return " ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + next(sql for sql in statements if "ORDER BY" in sql)))


def test_the_unread_list_pages_correctly_whichever_way_it_is_read(conn, user_id):
    mine = [feeds.create(conn, user_id, url=f"https://{n}.example.com/feed", title=n) for n in ("a", "b")]
    for i in range(30):
        articles.insert_new(conn, mine[i % 2], [_article(f"m{i}", i // 3)], fetched_at=1)
    expected = [row[0] for row in conn.execute("SELECT id FROM articles ORDER BY published_at DESC, id DESC")]

    # On your own, the list walks the unread-by-date index and stops after a page.
    assert "idx_articles_unread_pub" in _all_unread_plan(conn, user_id)
    assert "TEMP B-TREE" not in _all_unread_plan(conn, user_id)
    assert _pages(conn, user_id, "newest") == expected
    assert _pages(conn, user_id, "oldest") == expected[::-1]

    # With someone else's feeds on the server, it goes through your feeds instead, with the same result.
    other = users.upsert(conn, sub="sub-bob", email="bob@example.com", name="Bob", picture=None)
    theirs = feeds.create(conn, other, url="https://c.example.com/feed", title="c")
    for i in range(30):
        articles.insert_new(conn, theirs, [_article(f"t{i}", i)], fetched_at=1)
    assert "idx_articles_unread_pub" not in _all_unread_plan(conn, user_id)
    assert _pages(conn, user_id, "newest") == expected
    assert _pages(conn, user_id, "oldest") == expected[::-1]


def test_indexing_an_article_twice_keeps_one_search_entry(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    articles.insert_new(conn, feed_id, [_article("g1", 1, title="Nudibranch news")], fetched_at=2)
    article_id = conn.execute("SELECT id FROM articles").fetchone()[0]
    search.index_article(conn, article_id, "Nudibranch news", "")
    assert conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0] == 1


def test_a_feed_behind_a_caching_proxy_that_answers_203_still_parses():
    rss = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>A</title><guid>a</guid></item></channel></rss>'

    async def main():
        transport = httpx.MockTransport(lambda request: httpx.Response(203, content=rss, headers={"content-type": "application/rss+xml"}))
        async with httpx.AsyncClient(transport=transport) as client:
            return await Fetcher(client).fetch("https://x.example.com/feed")

    assert [entry.title for entry in asyncio.run(main()).feed.entries] == ["A"]


def test_a_big_bookmark_import_saves_everything_in_batches(tmp_path, monkeypatch):
    db = Database(tmp_path / "feedstash.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="sub-ann", email="ann@example.com", name="Ann", picture=None)
    monkeypatch.setattr(bookmarks, "IMPORT_BATCH", 3)
    links = [bookmarks.ImportedLink(url=f"https://example.com/{n % 8}") for n in range(10)]
    result = bookmarks.import_links(db, user_id, links)
    assert (result.added, result.already_saved) == (8, 2)
    with db.transaction() as conn:
        assert len(items.existing_link_urls(conn, user_id, [f"https://example.com/{n}" for n in range(10)])) == 8
