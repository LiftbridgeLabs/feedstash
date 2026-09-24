import sqlite3
from email.message import EmailMessage

import pytest

from app.crypto import SecretBox
from app.db import Database
from app.db.models import ItemFilter
from app.db.repositories import items as items_repo
from app.db.repositories import mail as mail_repo
from app.db.repositories import stash_folders, users
from app.images import ImageStore
from app.mail.imap import MailError
from app.mail.parse import parse_message, sender_allowed
from app.services import mail as mail_service
from app.services.mail import check_account
from support.images import PNG


def message(
    subject="A note", body="Hello", sender="me@example.com", message_id="<one@example.com>", html=None, image=None
) -> bytes:
    mail = EmailMessage()
    mail["Subject"] = subject
    mail["From"] = sender
    mail["Message-ID"] = message_id
    mail.set_content(body)
    if html:
        mail.add_alternative(html, subtype="html")
    if image:
        mail.add_attachment(image, maintype="image", subtype="png", filename="shot.png")
    return mail.as_bytes()


class FakeMailbox:
    """Stands in for an IMAP connection: hands over messages and remembers what was marked read."""

    def __init__(self, messages: list[bytes]):
        self.messages = messages
        self.seen: list[bytes] = []
        self.config = None

    def __call__(self, config):
        self.config = config
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def unseen(self, limit=25):
        return [(str(index).encode(), raw) for index, raw in enumerate(self.messages)][:limit]

    def mark_seen(self, uid):
        self.seen.append(uid)


def test_a_message_becomes_a_title_tags_a_body_and_links():
    raw = message(
        subject="Reef guide #diving #reading",
        body="Worth reading: https://example.com/reefs and https://example.com/list?unsubscribe=1",
        html='<p>Worth <a href="https://example.com/reefs">reading</a></p>',
        image=PNG,
    )
    mail = parse_message(raw)
    assert mail.subject == "Reef guide #diving #reading"  # markers are read when the item is saved
    assert mail.sender == "me@example.com"
    assert "Worth reading" in mail.body
    assert mail.links == ["https://example.com/reefs"]  # the unsubscribe link is left out
    assert mail.image == PNG


def test_a_message_with_only_html_and_no_subject():
    mail = EmailMessage()
    mail["From"] = "Someone <SOMEONE@Example.com>"
    mail.set_content("<h1>Title</h1><p>Body text</p>", subtype="html")
    parsed = parse_message(mail.as_bytes())
    assert parsed.subject == "(no subject)"
    assert parsed.body == "Title Body text"
    assert parsed.sender == "someone@example.com"


def test_who_may_send():
    assert sender_allowed("me@example.com", [])  # nothing configured: anything in the mailbox counts
    assert sender_allowed("me@example.com", ["me@example.com"])
    assert sender_allowed("me@example.com", ["@example.com"])
    assert sender_allowed("anyone@elsewhere.com", ["*"])
    assert not sender_allowed("someone@elsewhere.com", ["me@example.com", "@example.com"])


def test_secrets_survive_a_round_trip_and_stay_shut_without_the_key():
    box = SecretBox("the-server-key")
    stored = box.encrypt("app-password")
    assert stored != "app-password"
    assert box.decrypt(stored) == "app-password"
    assert SecretBox("a-different-key").decrypt(stored) is None
    assert box.decrypt("not-encrypted-at-all") is None


@pytest.fixture
def mailbox_setup(tmp_path):
    """A database with one account that has a mailbox connected."""
    db = Database(tmp_path / "mail.db")
    db.initialize()
    images = ImageStore(tmp_path / "uploads")
    secrets = SecretBox("test-key")
    with db.transaction() as conn:
        user_id = users.upsert(conn, sub="sub-ann", email="ann@example.com", name="Ann", picture=None)
        account = mail_repo.save(
            conn, user_id, host="imap.example.com", port=993, username="stash@example.com",
            password=secrets.encrypt("app-password"), folder="INBOX", allowed_senders=[], enabled=True, now=100,
        )
    return db, images, secrets, account


def test_checking_a_mailbox_saves_what_is_in_it_once(mailbox_setup):
    db, images, secrets, account = mailbox_setup
    box = FakeMailbox([message(subject="Reef guide $Diving #diving", body="https://example.com/reefs")])

    assert check_account(db, images, secrets, account, open_mailbox=box) == 1
    assert box.seen == [b"0"]  # read, so it won't come back
    assert box.config.password == "app-password"  # decrypted for the connection, not stored in the clear

    with db.transaction() as conn:
        (item,) = items_repo.search(conn, account.user_id, ItemFilter())
        assert (item.type, item.title, item.source) == ("email", "Reef guide", "email")
        assert item.tags == ["diving"]
        assert item.url == "https://example.com/reefs"
        assert stash_folders.get(conn, account.user_id, item.folder_id).name == "Diving"  # made on the way in
        assert mail_repo.get(conn, account.user_id).saved_count == 1

    # The same message again (a mailbox that didn't keep the read flag) isn't saved twice.
    assert check_account(db, images, secrets, account, open_mailbox=FakeMailbox(box.messages)) == 0
    with db.transaction() as conn:
        assert len(items_repo.search(conn, account.user_id, ItemFilter())) == 1


def test_mail_from_someone_else_is_left_alone(mailbox_setup, tmp_path):
    db, images, secrets, account = mailbox_setup
    with db.transaction() as conn:
        account = mail_repo.save(
            conn, account.user_id, host=account.host, port=account.port, username=account.username,
            password=account.password, folder=account.folder, allowed_senders=["me@example.com"], enabled=True,
            now=200,
        )
    box = FakeMailbox([
        message(sender="stranger@elsewhere.com", message_id="<a@x>"),
        message(sender="me@example.com", message_id="<b@x>", subject="Mine"),
    ])
    assert check_account(db, images, secrets, account, open_mailbox=box) == 1
    assert box.seen == [b"0", b"1"]  # both marked read, so neither is looked at again
    with db.transaction() as conn:
        (item,) = items_repo.search(conn, account.user_id, ItemFilter())
        assert item.title == "Mine"


def test_a_password_this_server_cannot_read_asks_to_be_entered_again(mailbox_setup):
    db, images, _, account = mailbox_setup
    with pytest.raises(MailError, match="Enter it again"):
        check_account(db, images, SecretBox("some-other-key"), account, open_mailbox=FakeMailbox([]))
    with db.transaction() as conn:
        assert "Enter it again" in mail_repo.get(conn, account.user_id).last_error


def test_a_message_that_fails_for_a_passing_reason_stays_unread_and_is_saved_next_time(mailbox_setup, monkeypatch):
    db, images, secrets, account = mailbox_setup
    box = FakeMailbox([message(subject="Keep me", message_id="<keep@x>")])
    real_save = mail_service.save_message

    def busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(mail_service, "save_message", busy)
    assert check_account(db, images, secrets, account, open_mailbox=box) == 0
    assert box.seen == []  # not marked read, so it isn't lost
    with db.transaction() as conn:
        assert "tried again" in mail_repo.get(conn, account.user_id).last_error

    monkeypatch.setattr(mail_service, "save_message", real_save)
    assert check_account(db, images, secrets, account, open_mailbox=box) == 1
    assert box.seen == [b"0"]
    with db.transaction() as conn:
        assert mail_repo.get(conn, account.user_id).last_error is None


def test_remembered_message_ids_are_forgotten_after_a_while(mailbox_setup):
    db, _, _, account = mailbox_setup
    with db.transaction() as conn:
        mail_repo.remember(conn, account.id, "<old@x>", now=1_000)
        mail_repo.remember(conn, account.id, "<new@x>", now=9_000)
        assert mail_repo.forget_seen(conn, seen_before=5_000) == 1
        assert not mail_repo.already_saved(conn, account.id, "<old@x>")
        assert mail_repo.already_saved(conn, account.id, "<new@x>")
