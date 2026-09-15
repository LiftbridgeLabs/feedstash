import httpx


def test_the_server_says_which_release_it_is(start_server):
    server = start_server(FEEDSTASH_VERSION="1.2.3")
    assert httpx.get(server.base_url + "/api/health").json()["version"] == "1.2.3"
    assert server.login().get("/api/tree").json()["version"] == "1.2.3"


def test_a_checkout_without_a_release_is_dev(api):
    assert api.get("/api/tree").json()["version"] == "dev"


def test_browsers_recheck_the_app_files_after_an_update(server):
    for path in ("/static/js/main.js", "/static/style.css", "/static/icon.svg"):
        response = httpx.get(server.base_url + path)
        assert response.headers["cache-control"] == "no-cache", path
        assert response.headers.get("etag"), path
