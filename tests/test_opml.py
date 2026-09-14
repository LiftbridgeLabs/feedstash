import time
import urllib.request


def test_export_includes_folders_and_feeds(api, subscriptions):
    response = api.get("/api/opml/export")
    assert response.headers["content-disposition"].startswith("attachment")
    assert 'text="Blogs"' in response.text
    assert f'xmlUrl="{subscriptions.feed_server}/posts.atom"' in response.text


def test_import_adds_new_feeds_skips_known_ones_and_fetches_in_background(api, subscriptions):
    opml = urllib.request.urlopen(f"{subscriptions.feed_server}/subs.opml").read()
    result = api.post("/api/opml/import", files={"file": ("subs.opml", opml, "text/xml")}).json()
    assert result["added"] == 1
    assert result["skipped"] == 1

    # The imported feed points at a missing file, so the background fetch should record an error.
    deadline = time.monotonic() + 20
    loose = None
    while time.monotonic() < deadline:
        loose = next(f for f in api.get("/api/tree").json()["feeds"] if f["url"].endswith("/missing.xml"))
        if loose["last_error"]:
            break
        time.sleep(0.5)
    assert loose["last_error"] and "404" in loose["last_error"]


def test_import_rejects_invalid_files(api):
    response = api.post("/api/opml/import", files={"file": ("x.opml", b"not xml", "text/xml")})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
