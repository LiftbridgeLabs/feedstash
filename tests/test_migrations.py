"""A database created by the first release must upgrade in place when the server starts."""

import sqlite3

from support.legacy import make_legacy_db


def schema_version(path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_legacy_database_is_upgraded_in_place_keeping_alphabetical_order(start_server, tmp_path):
    db_path = tmp_path / "legacy.db"
    make_legacy_db(db_path)
    api = start_server(db_path=db_path).login()

    tree = api.get("/api/tree").json()
    assert [f["name"] for f in tree["folders"]] == ["Alpha", "beta", "gamma"]
    beta = next(f["id"] for f in tree["folders"] if f["name"] == "beta")
    assert [f["title"] for f in tree["feeds"] if f["folder_id"] == beta] == ["alpha", "Echo", "zulu"]
    assert [f["title"] for f in tree["feeds"] if f["folder_id"] is None] == ["a", "b"]
    articles = api.get("/api/articles", params={"scope": "all", "unread_only": "false"}).json()["articles"]
    assert [a["title"] for a in articles] == ["Kept"]
    assert schema_version(db_path) == 10


def test_upgraded_database_keeps_custom_order_across_restarts(start_server, tmp_path):
    db_path = tmp_path / "legacy.db"
    make_legacy_db(db_path)
    first = start_server(db_path=db_path)
    api = first.login()
    reversed_ids = [f["id"] for f in api.get("/api/tree").json()["folders"]][::-1]
    api.post("/api/folders/reorder", json={"ids": reversed_ids})
    first.stop()

    again = start_server(db_path=db_path).login()
    assert [f["id"] for f in again.get("/api/tree").json()["folders"]] == reversed_ids
