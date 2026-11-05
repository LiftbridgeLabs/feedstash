"""Bringing in an export: odd shapes in the file, the cap on pictures, and email logins SMTP can't carry."""

import io
import json
import zipfile

import pytest

from app.db import Database
from app.db.repositories import users
from app.errors import InvalidInput
from app.images import ImageStore
from app.mail import smtp
from app.services import account_transfer
from support.images import PNG
from support.smtp import FakeSMTP


def zipped(account: dict, **pictures: bytes) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("account.json", json.dumps({"format": "feedstash-account", "version": 1, **account}))
        for name, data in pictures.items():
            archive.writestr(f"pictures/{name}", data)
    buffer.seek(0)
    return buffer


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / "reader.db")
    db.initialize()
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="s", email="s@example.com", name=None, picture=None)
    return db, ImageStore(tmp_path / "uploads"), user_id


def test_odd_shapes_in_a_file_are_skipped_not_a_crash(setup):
    db, images, user_id = setup
    counts = account_transfer.import_zip(db, images, user_id, zipped({"items": [
        "not an item", 5,
        {"type": "link", "title": "Odd", "url": "https://example.com", "created_at": 1, "tags": "oops", "links": 5,
         "images": 3, "page": "nope"},
        {"type": "unknown kind", "title": "Skipped"},
    ], "feeds": [{"url": 7}]}))
    assert counts.items == 1 and counts.feeds == 0


def test_pictures_adding_up_past_the_cap_stop_the_import_and_leave_nothing(setup, monkeypatch):
    db, images, user_id = setup
    monkeypatch.setattr(account_transfer, "MAX_PICTURES_BYTES", len(PNG) + 10)
    names = ["a" * 20 + ".png", "b" * 20 + ".png"]
    data = zipped({"items": [{"type": "screenshot", "title": "Two", "created_at": 1, "images": names}]},
                  **{name: PNG for name in names})
    with pytest.raises(InvalidInput, match="add up to more"):
        account_transfer.import_zip(db, images, user_id, data)
    assert not images.directory.exists() or list(images.directory.iterdir()) == []
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_a_login_smtp_cant_carry_is_explained():
    fake = FakeSMTP(require_auth=("user", "pässword"))
    try:
        settings = smtp.EmailSettings(host="127.0.0.1", port=fake.port, security="none", username="user",
                                      password="pässword", from_address="f@example.com")
        with pytest.raises(smtp.SendError, match="characters SMTP logins don't allow"):
            smtp.send(settings, smtp.message(settings, to="t@example.com", subject="s", text="t"))
    finally:
        fake.close()
