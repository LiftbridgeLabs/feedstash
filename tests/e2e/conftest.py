"""Browser tests. Skipped unless READER_E2E_BROWSER points at a Chrome or Edge executable."""

import json
import os
import subprocess
import time
import urllib.request

import pytest

from conftest import free_port
from e2e.cdp import Page


def _launch(executable: str, profile, attempt_seconds: float) -> tuple[subprocess.Popen, str | None]:
    """Starts the browser and waits for a page to drive. Returns the process and the page's debugger URL (None if
    it didn't come up in time)."""
    port = free_port()
    # GitHub's Ubuntu runners don't allow Chrome's sandbox; the pages under test are our own.
    sandbox = ["--no-sandbox"] if os.environ.get("CI") else []
    process = subprocess.Popen([
        executable, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
        "--no-first-run", "--disable-extensions", "--window-size=1400,900", *sandbox, "about:blank",
    ])
    deadline = time.monotonic() + attempt_seconds
    while time.monotonic() < deadline and process.poll() is None:
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
            ws_url = next((t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page"), None)
            if ws_url:
                return process, ws_url
            # Up, but without a page yet (it happens on a busy runner): open one rather than wait.
            request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
            json.load(urllib.request.urlopen(request, timeout=2))
        except OSError:
            time.sleep(0.25)
    return process, None


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
def browser_page(tmp_path):
    executable = os.environ.get("READER_E2E_BROWSER")
    if not executable:
        pytest.skip("set READER_E2E_BROWSER to a Chrome/Edge executable to run browser tests")
    # A slow start on a busy CI runner used to fail a test (and a release) now and then: try a few times.
    for attempt in range(3):
        process, ws_url = _launch(executable, tmp_path / f"profile-{attempt}", attempt_seconds=30)
        if ws_url:
            break
        _stop(process)
    assert ws_url, "browser didn't expose a debuggable page after 3 tries"
    try:
        page = Page(ws_url)
        page.viewport(1400, 900)
        yield page
        page.close()
    finally:
        _stop(process)


@pytest.fixture
def reader(browser_page, server, subscriptions):
    """The app, signed in, showing All with both test feeds loaded. Fails the test on any JS error."""
    page = browser_page
    page.goto(server.base_url + "/auth/login")
    assert page.wait_for("!!window.reader && document.querySelectorAll('.item').length >= 40", timeout=20)
    yield page
    assert not page.errors, page.errors
