"""The mailbox connection checks the mail server's certificate and name."""

import imaplib
import ssl

import pytest

from app.mail import imap


def test_the_mail_servers_certificate_is_checked(monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    def fake_imap4_ssl(host, port, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(imaplib, "IMAP4_SSL", fake_imap4_ssl)
    with pytest.raises(Stop):
        with imap.Mailbox(imap.MailboxConfig(host="mail.example.com", port=993, username="u", password="p")):
            pass
    context = seen["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
