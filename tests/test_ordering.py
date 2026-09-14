def folder_ids(api):
    return [f["id"] for f in api.get("/api/tree").json()["folders"]]


def feeds_in(api, folder_id):
    return [f["id"] for f in api.get("/api/tree").json()["feeds"] if f["folder_id"] == folder_id]


def create_folders(api, *names):
    return [api.post("/api/folders", json={"name": name}).json()["id"] for name in names]


def test_new_folders_are_appended_not_sorted(api):
    create_folders(api, "Zeta", "Alpha", "Mid")
    assert [f["name"] for f in api.get("/api/tree").json()["folders"]] == ["Zeta", "Alpha", "Mid"]


def test_partial_folder_reorder_keeps_the_rest_in_order(api):
    a, b, c, d = create_folders(api, "A", "B", "C", "D")
    assert api.post("/api/folders/reorder", json={"ids": [d, b]}).status_code == 200
    assert folder_ids(api) == [d, b, a, c]


def test_reorder_rejects_unknown_or_duplicate_ids(api, subscriptions):
    tech_folder = subscriptions.tech_folder["id"]
    assert api.post("/api/folders/reorder", json={"ids": [999999]}).status_code == 400
    assert api.post("/api/folders/reorder", json={"ids": [tech_folder, tech_folder]}).status_code == 400
    assert api.post("/api/feeds/reorder", json={"folder_id": None, "ids": [999999]}).status_code == 400
    assert api.post("/api/feeds/reorder", json={"folder_id": 999999, "ids": [subscriptions.tech["id"]]}).status_code == 404


def test_reorder_feeds_within_and_across_folders(api, subscriptions):
    tech, atom = subscriptions.tech["id"], subscriptions.atom["id"]
    (one,) = create_folders(api, "One")
    assert api.post("/api/feeds/reorder", json={"folder_id": one, "ids": [tech, atom]}).status_code == 200
    assert feeds_in(api, one) == [tech, atom]
    api.post("/api/feeds/reorder", json={"folder_id": one, "ids": [atom, tech]})
    assert feeds_in(api, one) == [atom, tech]
    assert feeds_in(api, subscriptions.tech_folder["id"]) == []


def test_moving_appends_and_renaming_keeps_position(api, subscriptions):
    tech, atom = subscriptions.tech["id"], subscriptions.atom["id"]
    (zeta,) = create_folders(api, "Zeta")
    api.patch(f"/api/feeds/{atom}", json={"folder_id": zeta})
    api.patch(f"/api/feeds/{tech}", json={"folder_id": zeta})
    assert feeds_in(api, zeta) == [atom, tech]
    api.patch(f"/api/feeds/{atom}", json={"title": "Renamed"})
    assert feeds_in(api, zeta) == [atom, tech]


def test_deleting_a_folder_keeps_its_feed_order(api, subscriptions):
    tech, atom = subscriptions.tech["id"], subscriptions.atom["id"]
    (zeta,) = create_folders(api, "Zeta")
    api.post("/api/feeds/reorder", json={"folder_id": zeta, "ids": [atom, tech]})
    api.delete(f"/api/folders/{zeta}")
    assert feeds_in(api, None)[-2:] == [atom, tech]


def test_opml_export_follows_custom_order(api, subscriptions):
    api.post("/api/folders/reorder", json={"ids": [subscriptions.blogs_folder["id"], subscriptions.tech_folder["id"]]})
    opml = api.get("/api/opml/export").text
    assert opml.index('text="Blogs"') < opml.index('text="Tech"')
