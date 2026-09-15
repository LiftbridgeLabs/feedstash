import httpx


def test_the_server_says_which_release_it_is(start_server):
    server = start_server(FEEDSTASH_VERSION="1.2.3")
    assert httpx.get(server.base_url + "/api/health").json()["version"] == "1.2.3"
    assert server.login().get("/api/tree").json()["version"] == "1.2.3"


def test_a_checkout_without_a_release_is_dev(api):
    assert api.get("/api/tree").json()["version"] == "dev"
