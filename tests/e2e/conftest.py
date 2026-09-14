"""Browser tests. Skipped unless READER_E2E_BROWSER points at a Chrome or Edge executable."""

import json
import os
import subprocess
import time
import urllib.request

import pytest

from conftest import free_port
from e2e.cdp import Page


@pytest.fixture
def browser_page(tmp_path):
    executable = os.environ.get("READER_E2E_BROWSER")
    if not executable:
        pytest.skip("set READER_E2E_BROWSER to a Chrome/Edge executable to run browser tests")
    port = free_port()
    process = subprocess.Popen([
        executable, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={tmp_path / 'profile'}",
        "--no-first-run", "--disable-extensions", "--window-size=1400,900", "about:blank",
    ])
    try:
        ws_url = None
        deadline = time.monotonic() + 20
        while not ws_url and time.monotonic() < deadline:
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1))
                ws_url = next((t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page"), None)
            except OSError:
                time.sleep(0.2)
        assert ws_url, "browser didn't expose a debuggable page"
        page = Page(ws_url)
        page.viewport(1400, 900)
        yield page
        page.close()
    finally:
        process.terminate()
        process.wait(timeout=15)


@pytest.fixture
def reader(browser_page, server, subscriptions):
    """The app, signed in, showing All with both test feeds loaded. Fails the test on any JS error."""
    page = browser_page
    page.goto(server.base_url + "/auth/login")
    assert page.wait_for("!!window.reader && document.querySelectorAll('.item').length >= 40", timeout=20)
    yield page
    assert not page.errors, page.errors
