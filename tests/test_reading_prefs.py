import httpx


def test_how_long_read_articles_are_kept_is_a_personal_setting(api, server):
    assert api.get("/api/me").json()["read_retention_days"] == 30
    updated = api.patch("/api/account", json={"read_retention_days": 7})
    assert updated.status_code == 200, updated.text
    assert updated.json()["read_retention_days"] == 7
    assert api.get("/api/me").json()["read_retention_days"] == 7
    assert api.patch("/api/account", json={"read_retention_days": 0}).json()["read_retention_days"] == 0
    assert api.patch("/api/account", json={"read_retention_days": -1}).status_code == 400

    token = api.post("/api/tokens", json={"clientName": "phone"}).json()["token"]
    with_token = httpx.patch(server.base_url + "/api/account", json={"read_retention_days": 1},
                             headers={"Authorization": f"Bearer {token}"})
    assert with_token.status_code == 403  # preferences are changed from the web app
