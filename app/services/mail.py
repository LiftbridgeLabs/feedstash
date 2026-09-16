"""Checking the mailbox someone connected, and saving what arrives there into their stash.

FeedStash reaches out to the mailbox, so nothing has to reach in: this works on a server with no ports open,
behind a reverse proxy that asks for its own sign-in, or on a home LAN.
"""

import asyncio
import contextlib
import logging

from app.clock import now
from app.crypto import SecretBox
from app.db import Database
from app.db.models import ItemLink, MailAccount
from app.db.repositories import mail as mail_repo
from app.errors import InvalidInput
from app.images import ImageStore
from app.mail.imap import Mailbox, MailboxConfig, MailError
from app.mail.parse import ParsedMail, parse_message, sender_allowed
from app.services import stash

log = logging.getLogger("feedstash.mail")

FIRST_CHECK_SECONDS = 15


def mailbox_config(account: MailAccount, secrets: SecretBox) -> MailboxConfig:
    password = secrets.decrypt(account.password)
    if password is None:
        raise MailError("This server can't read the saved password any more. Enter it again to reconnect.")
    return MailboxConfig(
        host=account.host, port=account.port, username=account.username, password=password, folder=account.folder
    )


def save_message(db: Database, images: ImageStore, account: MailAccount, mail: ParsedMail) -> bool:
    """Saves one message as a stash item. False when it was already saved, or the sender isn't allowed."""
    if not sender_allowed(mail.sender, account.allowed_senders):
        log.info("Ignored mail from %s", mail.sender or "an unknown sender")
        return False
    if mail.message_id:
        with db.transaction() as conn:
            if mail_repo.already_saved(conn, account.id, mail.message_id):
                return False
    capture = stash.Capture(
        type="email", title=mail.subject, content=mail.body or None, image=mail.image,
        links=[ItemLink(url=url) for url in mail.links],
    )
    stash.capture(db, images, account.user_id, capture, default_source="email")
    if mail.message_id:
        with db.transaction() as conn:
            mail_repo.remember(conn, account.id, mail.message_id, now=now())
    return True


def check_account(
    db: Database, images: ImageStore, secrets: SecretBox, account: MailAccount, *, open_mailbox=Mailbox
) -> int:
    """Checks one mailbox and saves what's unread in it. Returns how many messages were saved.

    Every message is marked read afterwards, including ones that were skipped, so a message nobody wants
    doesn't get looked at forever.
    """
    saved = 0
    try:
        with open_mailbox(mailbox_config(account, secrets)) as box:
            for uid, raw in box.unseen():
                try:
                    if save_message(db, images, account, parse_message(raw)):
                        saved += 1
                except InvalidInput as exc:
                    log.warning("Couldn't save a message from %s: %s", account.username, exc)
                except Exception:
                    log.exception("Unexpected error saving a message from %s", account.username)
                box.mark_seen(uid)
    except MailError as exc:
        with db.transaction() as conn:
            mail_repo.record_check(conn, account.id, now=now(), error=str(exc))
        raise
    with db.transaction() as conn:
        mail_repo.record_check(conn, account.id, now=now(), error=None, saved=saved)
    return saved


class MailWorker:
    """Checks every connected mailbox on a timer. Run it in one process, like the feed refresher."""

    def __init__(self, db: Database, images: ImageStore, secrets: SecretBox, minutes: int):
        self._db = db
        self._images = images
        self._secrets = secrets
        self._seconds = max(60, minutes * 60)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="mail-check")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> int:
        """Checks every connected mailbox. Returns how many messages were saved."""
        accounts = await asyncio.to_thread(self._accounts)
        saved = 0
        for account in accounts:
            try:
                saved += await asyncio.to_thread(
                    check_account, self._db, self._images, self._secrets, account
                )
            except MailError as exc:
                log.warning("Mailbox %s: %s", account.username, exc)
            except Exception:
                log.exception("Unexpected error checking %s", account.username)
        return saved

    def _accounts(self) -> list[MailAccount]:
        with self._db.transaction() as conn:
            return mail_repo.enabled_accounts(conn)

    async def _run(self) -> None:
        await asyncio.sleep(FIRST_CHECK_SECONDS)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Checking mailboxes failed")
            await asyncio.sleep(self._seconds)
