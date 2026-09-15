import time

import pytest


def wait_for(api, item_id: int, done, timeout: float = 25) -> dict:
    deadline = time.monotonic() + timeout
    item = None
    while time.monotonic() < deadline:
        item = api.get(f"/api/items/{item_id}").json()
        if done(item):
            return item
        time.sleep(0.3)
    pytest.fail(f"page wasn't saved in time: {item}")


def saved(item: dict) -> bool:
    return bool(item["preview"]) and item["preview"]["status"] not in ("pending", "working")


def test_saved_links_get_a_preview_a_readable_copy_and_full_text_search(start_server, feed_server):
    api = start_server(PAGE_CAPTURE="true").login()
    created = api.post("/api/items", json={"type": "link", "url": f"{feed_server}/article.html"}).json()
    assert created["preview"]["status"] == "pending"

    item = wait_for(api, created["id"], saved)
    preview = item["preview"]
    assert preview["status"] == "ready", preview
    assert item["title"] == "The best reefs for beginner divers"  # filled in from the page
    assert preview["description"] == "Calm water, shallow walls and lots of fish."
    assert (preview["image"], preview["siteName"], preview["hasCopy"]) == (f"{feed_server}/img/reef.png", "Dive Mag", True)

    copy = api.get(f"/api/items/{item['id']}/page").json()
    assert "Bonaire lets you" in copy["html"]
    assert "<script" not in copy["html"] and "newsletter" not in copy["html"]
    assert f'src="{feed_server}/img/turtle.png"' in copy["html"]
    assert f'href="{feed_server}/shore"' in copy["html"]

    # Words that only appear in the page find the item, in other forms too ("nudibranch" finds "nudibranchs").
    assert [found["id"] for found in api.get("/api/items", params={"q": "nudibranch"}).json()] == [item["id"]]
    assert api.get("/api/items", params={"q": "sharks"}).json() == []


def test_addresses_that_arent_pages_or_cant_be_fetched(start_server, feed_server):
    api = start_server(PAGE_CAPTURE="true").login()
    text = api.post("/api/items", json={"type": "link", "url": f"{feed_server}/notes.txt", "title": "Notes"}).json()
    missing = api.post("/api/items", json={"type": "link", "url": f"{feed_server}/gone.html"}).json()

    skipped = wait_for(api, text["id"], saved)
    assert skipped["preview"]["status"] == "skipped" and "text/plain" in skipped["preview"]["error"]

    # A page that can't be fetched is retried later: it stays pending, with the reason.
    failing = wait_for(api, missing["id"], lambda item: item["preview"]["error"])
    assert failing["preview"]["status"] == "pending" and failing["preview"]["error"] == "HTTP 404"
    assert api.get(f"/api/items/{missing['id']}/page").json()["html"] is None
    assert api.post(f"/api/items/{missing['id']}/page/refresh").status_code == 200

    # A new address starts over, and the title the user gave is kept.
    changed = api.patch(f"/api/items/{text['id']}", json={"url": f"{feed_server}/article.html"}).json()
    assert changed["preview"]["status"] == "pending"
    ready = wait_for(api, text["id"], lambda item: item["preview"]["status"] == "ready")
    assert ready["title"] == "Notes"

    note = api.post("/api/items", json={"type": "snippet", "content": "No address here"}).json()
    assert note["preview"] is None
    assert api.get(f"/api/items/{note['id']}/page").status_code == 404
