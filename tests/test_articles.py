import sqlite3
import time

from conftest import unread_count


def test_pagination_is_complete_stable_and_ordered(api, subscriptions):
    first = api.get("/api/articles", params={"scope": "all", "limit": 40}).json()
    assert len(first["articles"]) == 40 and first["next_cursor"]
    second = api.get(
        "/api/articles",
        params={"scope": "all", "limit": 40, "cursor": first["next_cursor"], "max_id": first["max_id"]},
    ).json()
    items = first["articles"] + second["articles"]
    ids = [a["id"] for a in items]
    assert len(ids) == len(set(ids)) == 75
    assert second["next_cursor"] is None
    times = [a["published_at"] for a in items]
    assert times == sorted(times, reverse=True)

    oldest = api.get("/api/articles", params={"scope": "feed", "id": subscriptions.tech["id"], "order": "oldest"})
    assert oldest.json()["articles"][0]["title"].startswith("Tech story 14 ")
    assert api.get("/api/articles", params={"cursor": "garbage"}).status_code == 400


def test_article_content_is_sanitized_and_enriched(api, subscriptions):
    items = api.get("/api/articles", params={"scope": "feed", "id": subscriptions.tech["id"], "limit": 100}).json()
    story = next(a for a in items["articles"] if a["title"].startswith("Tech story 0 "))
    assert story["image"] == "https://example.com/img/0.jpg"
    content = api.get(f"/api/articles/{story['id']}").json()["content"]
    assert "<script" not in content
    assert "onclick" not in content
    assert "javascript:" not in content
    assert "Paragraph for story 0" in content

    atom_item = api.get("/api/articles", params={"scope": "feed", "id": subscriptions.atom["id"], "limit": 1})
    assert atom_item.json()["articles"][0]["url"] == f"{subscriptions.feed_server}/posts/0"
    assert api.get("/api/articles/999999").status_code == 404


def test_mark_older_than_with_undo(api, subscriptions):
    tech = subscriptions.tech["id"]
    marked = api.post("/api/mark-read", json={"scope": "feed", "id": tech, "older_than_hours": 12}).json()
    assert marked["marked"] == 10
    assert unread_count(api, tech) == 5
    undo = api.post("/api/mark-read/undo", json={"scope": "feed", "id": tech, "batch": marked["batch"]}).json()
    assert undo["restored"] == 10

    folder = subscriptions.tech_folder["id"]
    assert api.post("/api/mark-read", json={"scope": "folder", "id": folder, "older_than_hours": 24}).json()["marked"] == 7
    unread_only = api.get("/api/articles", params={"scope": "feed", "id": tech}).json()["articles"]
    everything = api.get("/api/articles", params={"scope": "feed", "id": tech, "unread_only": "false"}).json()["articles"]
    assert len(unread_only) == 8
    assert len(everything) == 15


def test_mark_all_only_covers_the_loaded_snapshot(api, subscriptions):
    atom = subscriptions.atom["id"]
    snapshot = api.get("/api/articles", params={"scope": "feed", "id": atom}).json()["max_id"]
    marked = api.post("/api/mark-read", json={"scope": "feed", "id": atom, "max_id": snapshot - 5}).json()
    assert marked["marked"] == 55
    assert unread_count(api, atom) == 5


def test_mark_individual_articles_and_read_later(api, subscriptions):
    article_id = api.get("/api/articles", params={"scope": "all", "limit": 1}).json()["articles"][0]["id"]
    assert api.post("/api/articles/mark", json={"ids": [article_id], "read": True}).json()["updated"] == 1
    assert api.post("/api/articles/mark", json={"ids": [article_id], "read": False}).json()["updated"] == 1
    assert api.post("/api/articles/mark", json={"ids": [999999], "read": True}).json()["updated"] == 0

    assert api.post(f"/api/articles/{article_id}/star", json={"starred": True}).json() == {"starred": True}
    starred = api.get("/api/articles", params={"scope": "starred"}).json()["articles"]
    assert [a["id"] for a in starred] == [article_id]
    assert starred[0]["starred"] is True
    assert api.get("/api/tree").json()["starred_count"] == 1
    assert api.post("/api/articles/999999/star", json={"starred": True}).status_code == 404


def test_new_count_reports_articles_that_arrived_after_loading(api, server, subscriptions):
    max_id = api.get("/api/articles", params={"scope": "all", "unread_only": "false", "limit": 1}).json()["max_id"]
    response = api.get("/api/articles/new-count", params={"since_id": max_id})
    assert response.status_code == 200
    assert response.json() == {"count": 0}

    tech, atom = subscriptions.tech["id"], subscriptions.atom["id"]
    now = int(time.time())
    with sqlite3.connect(server.db_path) as db:
        db.executemany(
            "INSERT INTO articles (feed_id, guid, title, published_at, fetched_at, read_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(tech, "fresh-a", "Fresh A", now, now, None), (tech, "fresh-b", "Fresh B", now, now, now)],
        )

    def count(**params):
        return api.get("/api/articles/new-count", params={"since_id": max_id, **params}).json()["count"]

    assert count() == 1
    assert count(unread_only="false") == 2
    assert count(scope="feed", id=tech) == 1
    assert count(scope="feed", id=atom) == 0
