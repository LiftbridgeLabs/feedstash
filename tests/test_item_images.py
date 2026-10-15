"""An item can hold several pictures: added, reordered, removed, and cleaned up with the item."""

import httpx

from support.images import PNG


def png(n: int):
    return [("image", (f"p{i}.png", PNG, "image/png")) for i in range(n)]


def served(api, path: str) -> int:
    return httpx.get(str(api.base_url.join(path))).status_code


def test_pictures_are_added_reordered_removed_and_deleted_with_the_item(api):
    created = api.post("/api/items", data={"type": "screenshot", "title": "Board"}, files=png(3))
    assert created.status_code == 201, created.text
    item = created.json()
    assert len(item["images"]) == 3 and item["imagePath"] == item["images"][0]
    item_id, first, second, third = item["id"], *item["images"]

    added = api.post(f"/api/items/{item_id}/images", files=png(2)).json()
    assert added["images"][:3] == [first, second, third] and len(added["images"]) == 5

    # Keep three, in a new order: the others are removed from disk, and imagePath follows the new first.
    kept = api.patch(f"/api/items/{item_id}", json={"images": [third, first, added["images"][4]]}).json()
    assert kept["images"] == [third, first, added["images"][4]] and kept["imagePath"] == third
    assert served(api, second) == 404 and served(api, added["images"][3]) == 404
    assert served(api, third) == 200
    assert api.get(f"/api/items/{item_id}").json()["images"] == kept["images"]

    # Only the item's own pictures can be kept; adding goes through the images endpoint.
    assert api.patch(f"/api/items/{item_id}", json={"images": ["/uploads/someone-else.png"]}).status_code == 400
    assert api.patch(f"/api/items/{item_id}", json={"images": "nope"}).status_code == 400

    # Deleting the item removes the pictures it still has.
    api.delete(f"/api/items/{item_id}")
    assert served(api, third) == 404


def test_removing_every_picture_leaves_an_item_without_one(api):
    item = api.post("/api/items", data={"type": "snippet", "content": "Pictures to drop"}, files=png(2)).json()
    emptied = api.patch(f"/api/items/{item['id']}", json={"images": []}).json()
    assert emptied["images"] == [] and emptied["imagePath"] is None
    assert all(served(api, path) == 404 for path in item["images"])


def test_notes_and_links_can_have_pictures_and_the_limit_holds(api):
    note = api.post("/api/items", data={"type": "snippet", "content": "With pictures"}, files=png(2)).json()
    assert len(note["images"]) == 2
    plain = api.post("/api/items", json={"type": "link", "url": "https://example.com"}).json()
    assert plain["images"] == [] and plain["imagePath"] is None

    many = api.post(f"/api/items/{plain['id']}/images", files=png(20))
    assert many.status_code == 200 and len(many.json()["images"]) == 20
    over = api.post(f"/api/items/{plain['id']}/images", files=png(1))
    assert over.status_code == 400 and "at most 20" in over.json()["error"]
    assert len(api.get(f"/api/items/{plain['id']}").json()["images"]) == 20

    bad = api.post(f"/api/items/{note['id']}/images", files=[("image", ("x.png", b"<html>", "image/png"))])
    assert bad.status_code == 400
    assert api.post(f"/api/items/{note['id']}/images", json={}).status_code == 400


def test_someone_else_cant_add_pictures_to_your_item(api, server):
    item = api.post("/api/items", json={"type": "snippet", "content": "mine"}).json()
    theirs = httpx.Client(base_url=server.base_url, headers={"X-Requested-With": "reader"}, timeout=30)
    assert theirs.post(f"/api/items/{item['id']}/images", files=png(1)).status_code == 401
