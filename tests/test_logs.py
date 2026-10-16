"""Settings → Logs: admins choose the log's level and size, and read or download it."""

import httpx

from conftest import CSRF_HEADERS

PASSWORD = "correct horse battery"


def test_an_admin_sets_the_log_reads_it_and_downloads_it(start_server):
    server = start_server(DEV_LOGIN="false")
    admin = httpx.Client(base_url=server.base_url, headers=CSRF_HEADERS, timeout=30)
    assert admin.post("/auth/setup", json={"email": "owner@example.com", "name": "Owner", "password": PASSWORD}).status_code == 200

    settings = admin.get("/api/admin/logs/settings").json()
    assert settings["level"] == "info" and settings["requests"] == "changes" and settings["directory"].endswith("logs")

    admin.post("/api/items", json={"type": "snippet", "content": "logged"}).raise_for_status()
    admin.get("/api/tree").raise_for_status()
    lines = admin.get("/api/admin/logs").json()["lines"]
    assert any('"POST /api/items' in line for line in lines)
    assert not any('"GET /api/tree' in line for line in lines), "plain reads aren't logged by default"

    changed = admin.put("/api/admin/logs/settings", json={"level": "debug", "requests": "all", "keep_files": 3, "max_mb": 25})
    assert changed.status_code == 200 and changed.json()["requests"] == "all"
    admin.get("/api/tree").raise_for_status()
    assert any('"GET /api/tree' in line for line in admin.get("/api/admin/logs").json()["lines"])
    assert admin.put("/api/admin/logs/settings", json={"level": "debug", "requests": "all", "keep_files": 0, "max_mb": 25}).status_code == 400

    download = admin.get("/api/admin/logs/download")
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert '"POST /api/items' in download.text

    # The choice outlives a restart.
    server.stop()
    again = start_server(db_path=server.db_path, DEV_LOGIN="false")
    admin = httpx.Client(base_url=again.base_url, headers=CSRF_HEADERS, timeout=30)
    admin.post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD}).raise_for_status()
    assert admin.get("/api/admin/logs/settings").json()["max_mb"] == 25


def test_only_admins_and_only_from_the_web_app(start_server):
    server = start_server(DEV_LOGIN="false")
    admin = httpx.Client(base_url=server.base_url, headers=CSRF_HEADERS, timeout=30)
    admin.post("/auth/setup", json={"email": "owner@example.com", "password": PASSWORD}).raise_for_status()
    admin.post("/api/accounts", json={"email": "kid@example.com", "password": "kid password"}).raise_for_status()
    kid = httpx.Client(base_url=server.base_url, headers=CSRF_HEADERS, timeout=30)
    kid.post("/auth/password", json={"email": "kid@example.com", "password": "kid password"}).raise_for_status()
    assert kid.get("/api/admin/logs").status_code == 403
    token = admin.post("/api/tokens", json={"clientName": "script"}).json()["token"]
    with_token = httpx.get(server.base_url + "/api/admin/logs", headers={"Authorization": f"Bearer {token}"})
    assert with_token.status_code == 403
