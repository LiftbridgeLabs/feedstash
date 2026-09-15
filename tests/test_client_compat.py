"""The clients (browser extension, email worker, Android and iOS apps) must keep working.
Each test sends requests shaped exactly like that client's code does."""

import re
import sqlite3

import httpx

from support.images import JPEG, PNG

# Fields the iOS app's Codable FeedStashItem requires (a missing or mistyped one fails decoding).
IOS_REQUIRED = {"id": int, "type": str, "source": str, "reviewed": bool, "archived": bool, "createdAt": str, "tags": list}
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def mint(api, client_name: str) -> str:
    response = api.post("/api/tokens", json={"clientName": client_name})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def token_client(server, token: str) -> httpx.Client:
    # No X-Requested-With header: real clients don't send one.
    return httpx.Client(base_url=server.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def assert_decodable_by_ios(item: dict) -> None:
    for key, kind in IOS_REQUIRED.items():
        assert isinstance(item[key], kind), (key, item)
    for key in ("title", "content", "url", "imagePath"):
        assert key in item
    assert ISO_TIME.match(item["createdAt"]), item["createdAt"]


def test_health_check_needs_no_token(server):
    response = httpx.get(server.base_url + "/api/health")
    assert response.status_code == 200 and response.json()["ok"] is True


def test_browser_extension_captures(api, server):
    extension = token_client(server, mint(api, "extension"))
    link = extension.post("/api/items", files={
        "type": (None, "link"), "url": (None, "https://example.com/page"), "title": (None, "Page"),
        "tags": (None, "dev, tocheck"), "source": (None, "extension"),
    })
    assert link.status_code == 201, link.text
    assert link.json()["source"] == "extension" and link.json()["tags"] == ["dev", "tocheck"]
    assert [entry["url"] for entry in link.json()["links"]] == ["https://example.com/page"]  # a lone url becomes the first link
    assert_decodable_by_ios(link.json())

    screenshot = extension.post("/api/items", files={
        "type": (None, "screenshot"), "url": (None, "https://example.com/page"),
        "image": ("screenshot.png", PNG, "image/png"), "source": (None, "extension"),
    })
    assert screenshot.status_code == 201, screenshot.text
    assert screenshot.json()["imagePath"].endswith(".png")

    without_source = extension.post("/api/items", json={"type": "snippet", "content": "no source given"})
    assert without_source.json()["source"] == "extension"  # falls back to the token's client name


def test_email_worker_capture_with_hashtag_tags_and_attachment(api, server):
    worker = token_client(server, mint(api, "email-worker"))
    response = worker.post("/api/items", files={
        "type": (None, "email"), "title": (None, "Cool library"), "content": (None, "Body text"),
        "tags": (None, '["dev","tocheck"]'), "source": (None, "email"),
        "image": ("attachment.jpg", JPEG, "image/jpeg"),
    })
    assert response.status_code == 201, response.text
    assert response.json()["tags"] == ["dev", "tocheck"]
    assert response.json()["imagePath"].endswith(".jpg")


def test_android_share_with_a_generic_image_type(api, server):
    phone = token_client(server, mint(api, "android"))
    response = phone.post("/api/items", files={
        "type": (None, "screenshot"), "tags": (None, "[]"), "source": (None, "android"),
        "image": ("IMG_0001", PNG, "image/*"),
    })
    assert response.status_code == 201, response.text
    assert response.json()["imagePath"].endswith(".png")


def test_phone_review_flow(api, server):
    phone = token_client(server, mint(api, "ios"))
    item = phone.post("/api/items", json={"type": "link", "url": "https://example.com/r", "tags": ["x"], "source": "ios"}).json()
    listed = phone.get("/api/items", params={"reviewed": "false", "archived": "false"}).json()
    assert [i["id"] for i in listed] == [item["id"]]
    for entry in listed:
        assert_decodable_by_ios(entry)
    assert phone.patch(f"/api/items/{item['id']}", json={"reviewed": True}).json()["reviewed"] is True
    assert phone.get("/api/tags").json() == [{"name": "x", "count": 1}]
    assert phone.delete(f"/api/items/{item['id']}").status_code == 204


def test_bad_or_missing_tokens_get_401_with_an_error_message(server):
    bad = httpx.post(server.base_url + "/api/items", json={"type": "link", "url": "https://x.example.com"},
                     headers={"Authorization": "Bearer not-a-real-token"})
    assert bad.status_code == 401
    assert bad.json()["error"]
    anonymous = httpx.get(server.base_url + "/api/items")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]


def test_a_query_string_token_works_for_reads_only(api, server):
    token = mint(api, "reader")
    assert httpx.get(server.base_url + "/api/items", params={"token": token}).status_code == 200
    write = httpx.post(server.base_url + "/api/items", params={"token": token}, headers={"X-Requested-With": "reader"},
                       json={"type": "link", "url": "https://x.example.com"})
    assert write.status_code == 401


def test_tokens_are_listed_and_revoked_but_never_readable(api, server):
    token = mint(api, "extension")
    (listed,) = api.get("/api/tokens").json()
    assert listed["clientName"] == "extension"
    assert listed["tokenPreview"] == f"...{token[-4:]}"
    assert "token" not in listed
    with sqlite3.connect(server.db_path) as db:
        stored = db.execute("SELECT token_hash FROM api_tokens").fetchone()[0]
    assert token not in stored

    extension = token_client(server, token)
    assert extension.get("/api/items").status_code == 200
    assert extension.get("/api/tokens").json()[0]["lastUsedAt"] is not None
    assert extension.delete(f"/api/tokens/{listed['id']}").status_code == 400  # can't revoke the token in use
    assert api.delete(f"/api/tokens/{listed['id']}").status_code == 204
    assert extension.get("/api/items").status_code == 401
    assert api.post("/api/tokens", json={}).status_code == 400
