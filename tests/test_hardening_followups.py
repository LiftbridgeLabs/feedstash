

def test_a_server_set_to_public_addresses_follows_and_saves_nothing_on_its_own_network(start_server, feed_server):
    # The same feed an ordinary server follows (test_feeds.py) is on this machine, so this one refuses it.
    server = start_server(FETCH_PUBLIC_ONLY="true")
    api = server.login()
    refused = api.post("/api/feeds", json={"url": f"{feed_server}/tech.xml"})
    assert refused.status_code == 400 and "only fetches public addresses" in refused.json()["detail"]
    itself = api.post("/api/feeds", json={"url": f"{server.base_url}/api/health"})
    assert itself.status_code == 400 and "only fetches public addresses" in itself.json()["detail"]
    assert api.get("/api/tree").json()["feeds"] == []
    api.close()
