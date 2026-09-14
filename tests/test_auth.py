import httpx


def test_anonymous_visitors_get_the_login_page_with_security_headers(server):
    response = httpx.get(server.base_url + "/")
    assert "Continue as local user" in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_api_requires_sign_in(server):
    assert httpx.get(server.base_url + "/api/tree").status_code == 401


def test_state_changes_require_the_csrf_header(server):
    assert httpx.post(server.base_url + "/api/folders", json={"name": "x"}).status_code == 403


def test_dev_login_then_logout(api):
    assert 'id="articles"' in api.get("/").text
    assert api.get("/api/me").json()["email"] == "dev@localhost"
    assert api.post("/auth/logout").status_code == 200
    assert api.get("/api/tree").status_code == 401
