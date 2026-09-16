"""The Google Reader API, driven the way reader apps drive it: a separate client with no session cookie and no
CSRF header, signed in with an email and an API token."""

import httpx

READING_LIST = "user/-/state/com.google/reading-list"
READ = "user/-/state/com.google/read"
STARRED = "user/-/state/com.google/starred"
EMAIL = "dev@localhost"


def new_token(api, name: str = "NetNewsWire") -> str:
    return api.post("/api/tokens", json={"clientName": name}).json()["token"]


def sign_in(server, api, *, prefix: str = "") -> httpx.Client:
    login = httpx.post(
        f"{server.base_url}{prefix}/accounts/ClientLogin", data={"Email": EMAIL, "Passwd": new_token(api)}
    )
    assert login.status_code == 200, login.text
    auth = dict(line.split("=", 1) for line in login.text.strip().splitlines())["Auth"]
    return httpx.Client(
        base_url=f"{server.base_url}{prefix}", headers={"Authorization": f"GoogleLogin auth={auth}"}, timeout=30
    )


def unread_counts(reader) -> dict[str, int]:
    return {entry["id"]: entry["count"] for entry in reader.get("/reader/api/0/unread-count").json()["unreadcounts"]}


def test_signing_in_takes_your_email_and_an_api_token(server, api):
    token = new_token(api, "Reeder")
    login_url = f"{server.base_url}/accounts/ClientLogin"
    assert httpx.post(login_url, data={"Email": EMAIL, "Passwd": "not-a-token"}).status_code == 403
    assert httpx.post(login_url, data={"Email": "someone@else.com", "Passwd": token}).status_code == 403
    accepted = httpx.post(login_url, data={"Email": "Dev@Localhost", "Passwd": token})
    assert accepted.status_code == 200 and f"Auth={token}" in accepted.text

    assert httpx.get(f"{server.base_url}/reader/api/0/user-info").status_code == 401
    reader = httpx.Client(base_url=server.base_url, headers={"Authorization": f"GoogleLogin auth={token}"})
    assert reader.get("/reader/api/0/user-info").json()["userEmail"] == EMAIL
    assert len(reader.get("/reader/api/0/token").text) == 57

    # Revoking the token in Settings locks the app out.
    token_id = next(t["id"] for t in api.get("/api/tokens").json() if t["clientName"] == "Reeder")
    api.delete(f"/api/tokens/{token_id}")
    assert reader.get("/reader/api/0/user-info").status_code == 401


def test_both_addresses_apps_are_given(server, api):
    for prefix in ("", "/api/greader.php"):
        reader = sign_in(server, api, prefix=prefix)
        assert reader.get("/reader/api/0/user-info").status_code == 200, prefix


def test_feeds_folders_and_unread_counts(server, api, subscriptions):
    reader = sign_in(server, api)
    subscribed = reader.get("/reader/api/0/subscription/list", params={"output": "json"}).json()["subscriptions"]
    tech = next(sub for sub in subscribed if sub["id"] == f"feed/{subscriptions.tech['id']}")
    assert tech["categories"] == [{"id": "user/-/label/Tech", "label": "Tech"}]
    assert tech["url"].endswith("/tech.xml")

    tags = [tag["id"] for tag in reader.get("/reader/api/0/tag/list").json()["tags"]]
    assert STARRED in tags and "user/-/label/Tech" in tags and "user/-/label/Blogs" in tags

    counts = unread_counts(reader)
    assert counts[READING_LIST] == 75 and counts["user/-/label/Tech"] == 15 and counts["user/-/label/Blogs"] == 60


def test_read_state_is_one_state_wherever_it_changes(server, api, subscriptions):
    reader = sign_in(server, api)
    refs = reader.get(
        "/reader/api/0/stream/items/ids", params={"s": READING_LIST, "xt": READ, "n": 10000}
    ).json()["itemRefs"]
    assert len(refs) == 75
    first = [ref["id"] for ref in refs[:3]]
    long_ids = [f"tag:google.com,2005:reader/item/{int(article_id):016x}" for article_id in first]

    items = reader.post("/reader/api/0/stream/items/contents", data={"i": long_ids}).json()["items"]
    assert [item["id"] for item in items] == long_ids
    assert all(READING_LIST in item["categories"] and READ not in item["categories"] for item in items)

    # Read in the app shows as read in FeedStash, and read in FeedStash shows in the app.
    assert reader.post("/reader/api/0/edit-tag", data={"i": first[:2], "a": READ}).text == "OK"
    assert unread_counts(reader)[READING_LIST] == 73
    assert api.get(f"/api/articles/{first[0]}").json()["read"] is True
    api.post("/api/articles/mark", json={"ids": [int(first[0])], "read": False})
    assert unread_counts(reader)[READING_LIST] == 74
    reader.post("/reader/api/0/edit-tag", data={"i": first[1], "r": READ})
    assert unread_counts(reader)[READING_LIST] == 75

    assert reader.post("/reader/api/0/edit-tag", data={"i": long_ids[2], "a": STARRED}).text == "OK"
    starred = reader.get(f"/reader/api/0/stream/contents/{STARRED}").json()["items"]
    assert [item["id"] for item in starred] == [long_ids[2]] and STARRED in starred[0]["categories"]
    assert api.get("/api/tree").json()["starred_count"] == 1


def test_marking_a_folder_read_leaves_the_rest(server, api, subscriptions):
    reader = sign_in(server, api)
    assert reader.post("/reader/api/0/mark-all-as-read", data={"s": "user/-/label/Tech"}).text == "OK"
    counts = unread_counts(reader)
    assert counts["user/-/label/Tech"] == 0 and counts["user/-/label/Blogs"] == 60


def test_paging_through_a_stream(server, api, subscriptions):
    reader = sign_in(server, api)
    seen, continuation = [], None
    while True:
        params = {"s": READING_LIST, "n": 30, **({"c": continuation} if continuation else {})}
        page = reader.get("/reader/api/0/stream/items/ids", params=params).json()
        seen += [ref["id"] for ref in page["itemRefs"]]
        continuation = page.get("continuation")
        if not continuation:
            break
    assert len(seen) == 75 and len(set(seen)) == 75  # every article once, none skipped or repeated


def test_following_renaming_filing_and_unfollowing(server, api, feed_server):
    reader = sign_in(server, api)
    added = reader.post("/reader/api/0/subscription/quickadd", data={"quickadd": f"{feed_server}/tech.xml"}).json()
    assert added["numResults"] == 1
    stream = added["streamId"]

    assert reader.post("/reader/api/0/subscription/edit", data={
        "ac": "edit", "s": stream, "t": "Tech news", "a": "user/-/label/Reading",
    }).text == "OK"
    (subscription,) = reader.get("/reader/api/0/subscription/list").json()["subscriptions"]
    assert subscription["title"] == "Tech news" and subscription["categories"][0]["label"] == "Reading"

    reader.post("/reader/api/0/rename-tag", data={"s": "user/-/label/Reading", "dest": "user/-/label/Later"})
    assert [folder["name"] for folder in api.get("/api/tree").json()["folders"]] == ["Later"]
    reader.post("/reader/api/0/disable-tag", data={"s": "user/-/label/Later"})
    tree = api.get("/api/tree").json()
    assert tree["folders"] == [] and tree["feeds"][0]["folder_id"] is None  # the feed stays, uncategorized

    reader.post("/reader/api/0/subscription/edit", data={"ac": "unsubscribe", "s": stream})
    assert api.get("/api/tree").json()["feeds"] == []

    # Something that isn't a feed is reported, not treated as a failure of the call itself.
    not_a_feed = reader.post("/reader/api/0/subscription/quickadd", data={"quickadd": f"{feed_server}/plain.html"})
    assert not_a_feed.status_code == 200 and not_a_feed.json()["numResults"] == 0
