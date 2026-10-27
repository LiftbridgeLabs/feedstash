"""One account can never read or change another's data.

The owner sets up feeds, articles, a stash and its organizing, and an API token; then a second account tries every
route that takes an id with the owner's ids. Each attempt must get a 404 (or, for routes that act on a list of ids
or a whole scope, an answer that did nothing), and the owner's view must be exactly the same afterwards.

Both accounts sign in for real (passwords, DEV_LOGIN off). One server serves the whole module: if isolation holds,
no attempt changes anything, and the owner's view is compared before and after each one.
"""

import time
from types import SimpleNamespace

import httpx
import pytest

from conftest import CSRF_HEADERS, launch_server
from support.images import PNG

OWNER_PASSWORD = "owner password here"
OTHER_PASSWORD = "other password here"


def client(server, **headers) -> httpx.Client:
    return httpx.Client(base_url=server.base_url, headers={**CSRF_HEADERS, **headers}, timeout=30)


def ok(response: httpx.Response) -> dict | list:
    assert response.status_code in (200, 201), response.text
    return response.json()


@pytest.fixture(scope="module")
def world(request, tmp_path_factory, feed_server):
    server = launch_server(tmp_path_factory.mktemp("isolation"), DEV_LOGIN="false", PAGE_CAPTURE="true")
    request.addfinalizer(server.stop)  # straight away, so a failure while setting up doesn't leave it running
    owner = client(server)
    ok(owner.post("/auth/setup", json={"email": "owner@example.com", "name": "Owner", "password": OWNER_PASSWORD}))
    ok(owner.post("/api/accounts", json={"email": "other@example.com", "name": "Other", "password": OTHER_PASSWORD}))
    other = client(server)
    ok(other.post("/auth/password", json={"email": "other@example.com", "password": OTHER_PASSWORD}))
    other_token = ok(other.post("/api/tokens", json={"clientName": "Reader app"}))["token"]
    reader = httpx.Client(base_url=server.base_url, headers={"Authorization": f"GoogleLogin auth={other_token}"})

    # Feeds: Test Tech in Tech, all read in one batch (so undo has something to restore), its newest article starred;
    # Atom Blog in Blogs, unread.
    folder = ok(owner.post("/api/folders", json={"name": "Tech"}))
    feed = ok(owner.post("/api/feeds", json={"url": f"{feed_server}/tech.xml", "folder_id": folder["id"]}))
    blog = ok(owner.post("/api/feeds", json={"url": f"{feed_server}/site.html", "folder_name": "Blogs"}))
    article = ok(owner.get("/api/articles", params={"scope": "feed", "id": feed["id"]}))["articles"][0]["id"]
    batch = ok(owner.post("/api/mark-read", json={"scope": "feed", "id": feed["id"]}))["batch"]
    ok(owner.post(f"/api/articles/{article}/star", json={"starred": True}))
    unread = ok(owner.get("/api/articles", params={"scope": "feed", "id": blog["id"]}))["articles"][0]["id"]
    blog_folder = next(f["id"] for f in ok(owner.get("/api/tree"))["folders"] if f["name"] == "Blogs")

    # The stash: a saved page in a folder, tagged, plus a smart list, a rule and an API token.
    stash_folder = ok(owner.post("/api/stash/folders", json={"name": "Private"}))
    item = ok(owner.post("/api/items", json={
        "type": "link", "url": f"{feed_server}/article.html", "title": "Mine", "tags": "secret",
        "folderId": stash_folder["id"],
    }))
    deadline = time.monotonic() + 20
    while ok(owner.get(f"/api/items/{item['id']}/page"))["status"] in ("pending", "working"):
        assert time.monotonic() < deadline, "the owner's page was never saved"
        time.sleep(0.2)
    smart_list = ok(owner.post("/api/stash/lists", json={"name": "Secret things", "tag": "secret"}))
    rule = ok(owner.post("/api/stash/rules", json={"field": "title", "value": "Mine", "addTag": "ruled"}))
    token = ok(owner.post("/api/tokens", json={"clientName": "Owner's phone"}))

    # The other account's own item, to try filing into the owner's folder.
    their_item = ok(other.post("/api/items", json={"type": "snippet", "content": "Theirs"}))

    yield SimpleNamespace(
        server=server, owner=owner, other=other, reader=reader, feed_server=feed_server,
        folder=folder["id"], feed=feed["id"], blog=blog["id"], blog_folder=blog_folder, batch=batch, article=article,
        unread=unread,
        stash_folder=stash_folder["id"], item=item["id"], list=smart_list["id"], rule=rule["id"], token=token["id"],
        their_item=their_item["id"],
    )
    for c in (owner, other, reader):
        c.close()


FEED_FIELDS = ("id", "folder_id", "title", "position", "url", "site_url", "unread", "auto_stash", "full_text")


def owner_view(w) -> dict:
    """Everything the owner can see that another account could try to change."""
    get = lambda path, **params: ok(w.owner.get(path, params=params))  # noqa: E731
    tree = get("/api/tree")
    return {
        "folders": tree["folders"],
        "feeds": [{key: feed.get(key) for key in FEED_FIELDS} for feed in tree["feeds"]],
        "starred_count": tree["starred_count"],
        "unread": get("/api/articles/ids", state="unread")["ids"],
        "starred": get("/api/articles/ids", state="starred")["ids"],
        "all": get("/api/articles/ids", state="all")["ids"],
        "article": get(f"/api/articles/{w.article}"),
        "items": get("/api/items"),
        "archived": get("/api/items", archived="true"),
        "page": get(f"/api/items/{w.item}/page"),
        "tags": get("/api/tags"),
        "summary": get("/api/stash/summary"),
        "stash_folders": get("/api/stash/folders"),
        "lists": get("/api/stash/lists"),
        "rules": get("/api/stash/rules"),
        "tokens": get("/api/tokens"),
    }


def png():
    return {"image": ("picture.png", PNG, "image/png")}


# (name, request made by the other account, its status, its body). A body of None allows any body; a function checks
# it. Every request uses the owner's ids. Reordering with ids that aren't yours is refused as a whole (400).
NOT_FOUND = 404
CASES = [
    # Stash items
    ("get item", lambda w: w.other.get(f"/api/items/{w.item}"), NOT_FOUND, None),
    ("edit item", lambda w: w.other.patch(f"/api/items/{w.item}", json={"title": "Taken"}), NOT_FOUND, None),
    ("archive item", lambda w: w.other.patch(f"/api/items/{w.item}", json={"archived": True}), NOT_FOUND, None),
    ("delete item", lambda w: w.other.delete(f"/api/items/{w.item}"), NOT_FOUND, None),
    ("add pictures", lambda w: w.other.post(f"/api/items/{w.item}/images", files=png()), NOT_FOUND, None),
    ("saved page", lambda w: w.other.get(f"/api/items/{w.item}/page"), NOT_FOUND, None),
    ("save page again", lambda w: w.other.post(f"/api/items/{w.item}/page/refresh"), NOT_FOUND, None),
    ("save into their folder",
     lambda w: w.other.post("/api/items", json={"type": "snippet", "content": "x", "folderId": w.stash_folder}),
     NOT_FOUND, None),
    ("file into their folder",
     lambda w: w.other.patch(f"/api/items/{w.their_item}", json={"folderId": w.stash_folder}), NOT_FOUND, None),
    ("rename their tag", lambda w: w.other.post("/api/tags/rename", json={"name": "secret", "newName": "mine"}),
     NOT_FOUND, None),
    ("delete their tag", lambda w: w.other.post("/api/tags/delete", json={"names": ["secret"]}), NOT_FOUND, None),
    # Articles
    ("get article", lambda w: w.other.get(f"/api/articles/{w.article}"), NOT_FOUND, None),
    ("unstar article", lambda w: w.other.post(f"/api/articles/{w.article}/star", json={"starred": False}),
     NOT_FOUND, None),
    ("full text", lambda w: w.other.post(f"/api/articles/{w.article}/full-text"), NOT_FOUND, None),
    ("stash article", lambda w: w.other.post(f"/api/articles/{w.article}/stash"), NOT_FOUND, None),
    ("feed info", lambda w: w.other.get(f"/api/feeds/{w.feed}/stats"), NOT_FOUND, None),
    ("mark read", lambda w: w.other.post("/api/articles/mark", json={"ids": [w.unread], "read": True}),
     200, {"updated": 0}),
    ("mark unread", lambda w: w.other.post("/api/articles/mark", json={"ids": [w.article], "read": False}),
     200, {"updated": 0}),
    ("star many", lambda w: w.other.post("/api/articles/star", json={"ids": [w.unread], "starred": True}),
     200, {"updated": 0}),
    ("unstar many", lambda w: w.other.post("/api/articles/star", json={"ids": [w.article], "starred": False}),
     200, {"updated": 0}),
    ("article contents", lambda w: w.other.post("/api/articles/contents", json={"ids": [w.article, w.unread]}),
     200, []),
    ("mark their feed read", lambda w: w.other.post("/api/mark-read", json={"scope": "feed", "id": w.blog}),
     200, lambda body: body["marked"] == 0),
    ("mark their folder read",
     lambda w: w.other.post("/api/mark-read", json={"scope": "folder", "id": w.blog_folder}),
     200, lambda body: body["marked"] == 0),
    ("undo their batch", lambda w: w.other.post("/api/mark-read/undo", json={"scope": "all", "batch": w.batch}),
     200, {"restored": 0}),
    ("undo their batch in their feed",
     lambda w: w.other.post("/api/mark-read/undo", json={"scope": "feed", "id": w.feed, "batch": w.batch}),
     200, {"restored": 0}),
    ("refresh their feed", lambda w: w.other.post("/api/refresh", json={"scope": "feed", "id": w.feed}),
     200, {"feeds": 0, "new": 0}),
    # Feeds and folders
    ("rename feed", lambda w: w.other.patch(f"/api/feeds/{w.feed}", json={"title": "Taken"}), NOT_FOUND, None),
    ("move feed", lambda w: w.other.patch(f"/api/feeds/{w.feed}", json={"folder_id": None}), NOT_FOUND, None),
    ("auto-save feed", lambda w: w.other.patch(f"/api/feeds/{w.feed}", json={"auto_stash": True}), NOT_FOUND, None),
    ("change feed address",
     lambda w: w.other.patch(f"/api/feeds/{w.feed}", json={"url": f"{w.feed_server}/posts.atom"}), NOT_FOUND, None),
    ("unfollow feed", lambda w: w.other.delete(f"/api/feeds/{w.feed}"), NOT_FOUND, None),
    ("follow into their folder",
     lambda w: w.other.post("/api/feeds", json={"url": f"{w.feed_server}/tech.xml", "folder_id": w.folder}),
     NOT_FOUND, None),
    ("reorder their feeds",
     lambda w: w.other.post("/api/feeds/reorder", json={"folder_id": w.folder, "ids": [w.feed]}), NOT_FOUND, None),
    ("rename folder", lambda w: w.other.patch(f"/api/folders/{w.folder}", json={"name": "Taken"}), NOT_FOUND, None),
    ("delete folder", lambda w: w.other.delete(f"/api/folders/{w.folder}"), NOT_FOUND, None),
    ("delete folder and feeds", lambda w: w.other.delete(f"/api/folders/{w.folder}", params={"unfollow": "true"}),
     NOT_FOUND, None),
    ("reorder their folders",
     lambda w: w.other.post("/api/folders/reorder", json={"ids": [w.blog_folder, w.folder]}), 400, None),
    # Stash folders, smart lists, rules
    ("rename stash folder", lambda w: w.other.patch(f"/api/stash/folders/{w.stash_folder}", json={"name": "Taken"}),
     NOT_FOUND, None),
    ("delete stash folder", lambda w: w.other.delete(f"/api/stash/folders/{w.stash_folder}"), NOT_FOUND, None),
    ("reorder their stash folders",
     lambda w: w.other.post("/api/stash/folders/reorder", json={"ids": [w.stash_folder]}), 400, None),
    ("edit smart list", lambda w: w.other.patch(f"/api/stash/lists/{w.list}", json={"name": "Taken"}),
     NOT_FOUND, None),
    ("delete smart list", lambda w: w.other.delete(f"/api/stash/lists/{w.list}"), NOT_FOUND, None),
    ("smart list on their folder",
     lambda w: w.other.post("/api/stash/lists", json={"name": "x", "folderId": w.stash_folder}), NOT_FOUND, None),
    ("delete rule", lambda w: w.other.delete(f"/api/stash/rules/{w.rule}"), NOT_FOUND, None),
    ("rule into their folder",
     lambda w: w.other.post("/api/stash/rules", json={"field": "title", "value": "x", "folderId": w.stash_folder}),
     NOT_FOUND, None),
    ("apply rules", lambda w: w.other.post("/api/stash/rules/apply"), 200, {"changed": 0}),
    # API tokens
    ("rename token", lambda w: w.other.patch(f"/api/tokens/{w.token}", json={"clientName": "Taken"}), NOT_FOUND, None),
    ("revoke token", lambda w: w.other.delete(f"/api/tokens/{w.token}"), NOT_FOUND, None),
    # The Google Reader API, with the other account's token
    ("reader: mark read and unstar",
     lambda w: w.reader.post("/reader/api/0/edit-tag", data={
         "i": [str(w.unread), str(w.article)], "a": "user/-/state/com.google/read",
         "r": "user/-/state/com.google/starred"}), 200, None),
    ("reader: mark unread",
     lambda w: w.reader.post("/reader/api/0/edit-tag", data={
         "i": str(w.article), "r": "user/-/state/com.google/read"}), 200, None),
    ("reader: unsubscribe",
     lambda w: w.reader.post("/reader/api/0/subscription/edit", data={"ac": "unsubscribe", "s": f"feed/{w.feed}"}),
     NOT_FOUND, None),
    ("reader: rename feed",
     lambda w: w.reader.post("/reader/api/0/subscription/edit", data={"ac": "edit", "s": f"feed/{w.feed}", "t": "x"}),
     NOT_FOUND, None),
    ("reader: mark their feed read",
     lambda w: w.reader.post("/reader/api/0/mark-all-as-read", data={"s": f"feed/{w.blog}"}), 200, None),
    ("reader: their articles",
     lambda w: w.reader.get("/reader/api/0/stream/items/contents", params={"i": [str(w.article), str(w.unread)]}),
     200, lambda body: body["items"] == []),
]


@pytest.mark.parametrize(("attempt", "status", "body"), [pytest.param(*case[1:], id=case[0]) for case in CASES])
def test_another_account_cant_reach_the_owners_data(world, attempt, status, body):
    w = world
    before = owner_view(w)

    response = attempt(w)
    assert response.status_code == status, response.text
    if callable(body):
        assert body(response.json()), response.text
    elif body is not None:
        assert response.json() == body

    assert owner_view(w) == before
