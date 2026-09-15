from app.db.models import ItemFilter, NewArticle, Scope
from app.db.repositories import articles, feeds, items, pages, search
from app.pages.fetch import extract
from app.text import html_to_text


def add_link(conn, user_id, url="https://example.com/reef"):
    return items.create(conn, user_id, type="link", title=None, content=None, url=url, image_name=None,
                        source="test", tags=[], now=100)


def test_search_queries_keep_words_and_prefix_the_last_one():
    assert search.match_query("  Reef  guides ") == '"Reef" "guides"*'
    assert search.match_query("5_%") == '"5"'
    assert search.match_query("c'est") == '"c" "est"*'
    assert search.match_query('say "hi" OR NOT drop') == '"say" "hi" "OR" "NOT" "drop"*'
    assert search.match_query("%%") is None and search.match_query(None) is None


def test_html_becomes_searchable_text():
    assert html_to_text("<p>Fish &amp; chips</p><p>on the <b>beach</b></p>") == "Fish & chips on the beach"


def test_page_queue_retries_then_stores_the_page(conn, user_id):
    item = add_link(conn, user_id)
    assert item.page.status == "pending"
    note = items.create(conn, user_id, type="snippet", title=None, content="No address", url=None, image_name=None,
                        source="test", tags=[], now=100)
    assert note.page is None

    (job,) = pages.claim(conn, now=200, limit=5)
    assert (job.item_id, job.attempts) == (item.id, 1)
    assert pages.claim(conn, now=201, limit=5) == []  # already being fetched
    pages.save_failure(conn, job, now=210, error="HTTP 503")
    assert items.get(conn, user_id, item.id).page.error == "HTTP 503"
    assert pages.claim(conn, now=250, limit=5) == []  # waits a minute before retrying
    (retry,) = pages.claim(conn, now=270, limit=5)

    assert pages.save_ready(conn, retry, now=300, title="Reef guide", description="Calm water", image_url=None,
                            site_name="Dive Mag", text="Nudibranchs everywhere", html="<p>Nudibranchs everywhere</p>")
    items.set_title_if_missing(conn, item.id, "Reef guide")
    search.index_item(conn, item.id)
    ready = items.get(conn, user_id, item.id)
    assert (ready.title, ready.page.status, ready.page.has_copy) == ("Reef guide", "ready", True)
    assert [found.id for found in items.search(conn, user_id, ItemFilter(query="nudibranch"))] == [item.id]

    # A new address starts over, and a late result for the old one is ignored.
    items.update(conn, user_id, item.id, now=400, url="https://example.com/other")
    assert items.get(conn, user_id, item.id).page.status == "pending"
    assert not pages.save_ready(conn, retry, now=401, title="Old", description=None, image_url=None, site_name=None,
                                text=None, html=None)


def test_a_page_that_keeps_failing_gives_up(conn, user_id):
    item = add_link(conn, user_id)
    for attempt, when in enumerate((200, 300, 2000), start=1):
        (job,) = pages.claim(conn, now=when, limit=1)
        assert job.attempts == attempt
        pages.save_failure(conn, job, now=when, error="HTTP 500")
    assert items.get(conn, user_id, item.id).page.status == "failed"
    assert pages.claim(conn, now=10_000, limit=1) == []


def test_items_saved_before_pages_were_captured_get_queued_and_indexed(conn, user_id):
    item = add_link(conn, user_id)
    conn.execute("DELETE FROM item_pages")
    conn.execute("DELETE FROM items_fts")
    assert pages.queue_missing(conn, now=500) == 1
    assert search.backfill(conn) == (1, 0)
    assert items.get(conn, user_id, item.id).page.status == "pending"
    assert [found.id for found in items.search(conn, user_id, ItemFilter(query="reef"))] == [item.id]


def test_article_search_uses_the_article_text_and_forgets_removed_articles(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    articles.insert_new(conn, feed_id, [NewArticle(
        guid="g1", title="Weekly news", url=None, author=None, summary="", content="", image=None, published_at=1,
        search_text="Nudibranchs were spotted on the house reef",
    )], fetched_at=2)
    found = articles.page(conn, user_id, Scope("all"), unread_only=False, query="nudibranch reefs")
    assert [article.title for article in found.articles] == ["Weekly news"]
    feeds.delete(conn, user_id, feed_id)
    assert conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0] == 0


def test_extracting_a_page_keeps_the_article_and_drops_the_rest():
    page = extract(b"""<html><head><title>Reef guide</title>
        <meta property="og:description" content="Calm water."><meta property="og:image" content="/r.jpg"></head>
        <body><nav>Home Shop</nav><article><h1>Reef guide</h1>
        <p>Cozumel drift dives are gentle enough for a first trip, with visibility that often tops thirty metres.</p>
        <p>Bonaire lets you <a href="/shore">dive from the shore</a> almost anywhere along the coast.</p>
        <img src="img/t.jpg"></article><footer>Subscribe</footer></body></html>""", "https://dive.example.com/guide")
    assert page.description == "Calm water." and page.image_url == "https://dive.example.com/r.jpg"
    assert "Bonaire lets you" in page.text and "Subscribe" not in page.text
    assert 'href="https://dive.example.com/shore"' in page.html
    assert '<img src="https://dive.example.com/img/t.jpg"' in page.html
