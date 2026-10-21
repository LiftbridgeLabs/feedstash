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


def test_the_firefox_download_has_firefox_s_manifest(server):
    chrome = zipfile.ZipFile(io.BytesIO(httpx.get(server.base_url + "/downloads/feedstash-extension.zip").content))
    firefox_reply = httpx.get(server.base_url + "/downloads/feedstash-extension-firefox.zip")
    assert 'filename="feedstash-extension-firefox.zip"' in firefox_reply.headers["content-disposition"]
    firefox = zipfile.ZipFile(io.BytesIO(firefox_reply.content))
    chrome_manifest = json.loads(chrome.read("feedstash-extension/manifest.json"))
    firefox_manifest = json.loads(firefox.read("feedstash-extension-firefox/manifest.json"))
    # Chrome keeps its service worker; Firefox gets background scripts and an add-on id.
    assert chrome_manifest["background"] == {"service_worker": "background.js"}
    assert "browser_specific_settings" not in chrome_manifest
    assert firefox_manifest["background"] == {"scripts": ["common.js", "background.js"]}
    assert firefox_manifest["browser_specific_settings"]["gecko"]["id"] == "feedstash-capture@liftbridgelabs.app"
    # Everything else is the same extension.
    assert sorted(n.split("/", 1)[1] for n in chrome.namelist()) == sorted(n.split("/", 1)[1] for n in firefox.namelist())
