"""At the storage limit the mail worker leaves mail in the mailbox for later."""

import asyncio

from app.services.mail import MailWorker


class FullStorage:
    full = True


def test_a_full_server_does_not_check_mailboxes():
    worker = MailWorker(db=None, images=None, secrets=None, minutes=5, storage=FullStorage())
    worker._accounts = lambda: (_ for _ in ()).throw(AssertionError("mailboxes were checked"))
    assert asyncio.run(worker.run_once()) == 0
