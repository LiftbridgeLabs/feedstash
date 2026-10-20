"""Settings → Apps offers the browser extension and the Cloudflare email worker as downloads."""

import io
import json
import zipfile

import httpx


def test_the_browser_extension_downloads_as_a_zip_ready_to_load(server):
    response = httpx.get(server.base_url + "/downloads/feedstash-extension.zip")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert 'filename="feedstash-extension.zip"' in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    # One folder to choose with Load unpacked, with the manifest at its top.
    assert "feedstash-extension/manifest.json" in names
    assert all(name.startswith("feedstash-extension/") for name in names)
    assert not any(name.endswith(".md") for name in names)
    assert json.loads(archive.read("feedstash-extension/manifest.json"))["manifest_version"] == 3


def test_the_email_worker_says_where_it_comes_from_when_it_isnt_built(server):
    # A checkout doesn't bundle the worker; the Docker image does (the release workflow checks it's there).
    response = httpx.get(server.base_url + "/downloads/feedstash-email-worker.js")
    assert response.status_code in (200, 404)
    if response.status_code == 404:
        assert "Docker image" in response.text


def test_the_page_can_ask_which_downloads_there_are(server):
    available = httpx.get(server.base_url + "/downloads").json()
    assert available["extension"] is True
    worker = httpx.get(server.base_url + "/downloads/feedstash-email-worker.js")
    assert available["email_worker"] is (worker.status_code == 200)
