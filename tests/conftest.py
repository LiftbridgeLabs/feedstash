"""Black-box test harness.

Every test gets its own reader server (a real uvicorn process on a free port) with a fresh
database, plus a shared local HTTP server hosting the test feeds. Nothing here imports the app,
so these tests keep working however the code inside `app/` is organized.
"""

import functools
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import IO

import httpx
import pytest

from support.feedgen import write_feeds
from support.oidc import FakeOidcProvider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_COMMAND = ["-m", "uvicorn", "--factory", "app.main:create_app"]
CSRF_HEADERS = {"X-Requested-With": "reader"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def feed_server(tmp_path_factory) -> str:
    """Serves the generated test feeds; yields the base URL."""
    root = tmp_path_factory.mktemp("feeds")
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    write_feeds(root, base_url)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(_QuietHandler, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield base_url
    httpd.shutdown()


@dataclass
class ReaderServer:
    base_url: str
    db_path: Path
    process: subprocess.Popen
    log_path: Path
    log_file: IO[bytes] = field(repr=False)

    def login(self) -> httpx.Client:
        client = httpx.Client(base_url=self.base_url, headers=CSRF_HEADERS, timeout=30)
        response = client.get("/auth/login", follow_redirects=True)
        assert response.status_code == 200, response.text
        return client

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)
        self.log_file.close()


@pytest.fixture
def start_server(tmp_path):
    """Factory: start_server(db_path=None, **env) -> ReaderServer."""
    started: list[ReaderServer] = []

    def start(db_path: Path | None = None, **env: str) -> ReaderServer:
        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        db_path = db_path or tmp_path / f"reader-{port}.db"
        log_path = tmp_path / f"server-{port}.log"
        environment = {
            **os.environ,
            "DEV_LOGIN": "true",
            "BASE_URL": base_url,
            "DATABASE_PATH": str(db_path),
            "SECRET_KEY": "test-secret-key",
            **env,
        }
        # A test can list extra addresses around the server's own, e.g. BASE_URL="https://x.example.com,{server}".
        environment["BASE_URL"] = environment["BASE_URL"].replace("{server}", base_url)
        log_file = open(log_path, "wb")
        process = subprocess.Popen(
            [sys.executable, *APP_COMMAND, "--host", "127.0.0.1", "--port", str(port)],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        server = ReaderServer(base_url, db_path, process, log_path, log_file)
        started.append(server)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None:
            try:
                if httpx.get(base_url + "/healthz", timeout=1).status_code == 200:
                    return server
            except httpx.HTTPError:
                time.sleep(0.2)
        server.stop()
        pytest.fail(f"Reader server didn't start:\n{log_path.read_text(errors='replace')}")

    yield start
    for server in started:
        server.stop()


@pytest.fixture
def server(start_server) -> ReaderServer:
    return start_server()


@pytest.fixture
def api(server) -> httpx.Client:
    """A client signed in as the dev user."""
    client = server.login()
    yield client
    client.close()


@pytest.fixture
def oidc_provider() -> FakeOidcProvider:
    provider = FakeOidcProvider(free_port())
    provider.start()
    yield provider
    provider.stop()


@pytest.fixture
def subscriptions(api, feed_server) -> SimpleNamespace:
    """'Test Tech' (15 items) in folder Tech, and 'Atom Blog' (60 items, found via a web page) in folder Blogs."""
    tech_folder = api.post("/api/folders", json={"name": "Tech"}).json()
    tech = api.post("/api/feeds", json={"url": f"{feed_server}/tech.xml", "folder_id": tech_folder["id"]}).json()
    atom = api.post("/api/feeds", json={"url": f"{feed_server}/site.html", "folder_name": "Blogs"}).json()
    blogs_folder = next(f for f in api.get("/api/tree").json()["folders"] if f["name"] == "Blogs")
    return SimpleNamespace(
        feed_server=feed_server, tech=tech, atom=atom, tech_folder=tech_folder, blogs_folder=blogs_folder
    )


def unread_count(api: httpx.Client, feed_id: int) -> int:
    return next(f for f in api.get("/api/tree").json()["feeds"] if f["id"] == feed_id)["unread"]
