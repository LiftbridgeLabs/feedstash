"""Talking to an IMAP mailbox. Blocking on purpose: callers run it in a thread."""

import imaplib
import logging
import socket
import ssl
from collections.abc import Iterator
from dataclasses import dataclass, field

from app import netguard
from app.netguard import BlockedAddress, checked_addresses

log = logging.getLogger("feedstash.mail")

TIMEOUT = 30
MAX_PER_CHECK = 25  # messages saved per check, so a full mailbox doesn't arrive all at once


class MailError(Exception):
    """Something went wrong talking to the mailbox. The message is shown to the user."""


@dataclass(frozen=True, slots=True)
class MailboxConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)  # in the clear: decrypted by the caller; never in a log line
    folder: str = "INBOX"


class _CheckedIMAP4_SSL(imaplib.IMAP4_SSL):
    """Connects to an address the mail server's name resolved to, checked first (see app.netguard), instead of
    resolving the name again while connecting. The certificate is still checked against the name."""

    def _create_socket(self, timeout):
        error: OSError | None = None
        for address in checked_addresses(self.host, self.port):
            try:
                sock = socket.create_connection((address, self.port), timeout)
            except OSError as exc:
                error = exc
                continue
            return self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        raise error or OSError(f"Couldn't connect to {self.host}")


class Mailbox:
    """One IMAP connection. Use it as a context manager."""

    def __init__(self, config: MailboxConfig):
        self._config = config
        self._imap: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "Mailbox":
        config = self._config
        try:
            # imaplib's own default context checks neither the certificate nor the host name, so anyone on the
            # way could pose as the mail server and collect the password.
            # Only a server set to public addresses takes the checked connection; everyone else's mailbox is
            # reached exactly as before.
            connect = _CheckedIMAP4_SSL if netguard.public_only() else imaplib.IMAP4_SSL
            self._imap = connect(config.host, config.port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
        except BlockedAddress as exc:
            # The guard's words are about fetching; a mailbox is connected to.
            raise MailError(str(exc).replace("only fetches", "only connects to")
                            .replace("doesn't fetch", "doesn't connect to")) from exc
        except ssl.SSLCertVerificationError as exc:
            raise MailError(f"{config.host} didn't present a valid certificate for its name ({exc.verify_message})") from exc
        except (OSError, socket.timeout, imaplib.IMAP4.error) as exc:
            raise MailError(f"Couldn't reach {config.host}:{config.port} ({exc.__class__.__name__})") from exc
        try:
            self._imap.login(config.username, config.password)
        except imaplib.IMAP4.error as exc:
            self.close()
            raise MailError(_login_hint(exc)) from exc
        try:
            status, _ = self._imap.select(config.folder)
            if status != "OK":
                raise MailError(f"The mailbox has no folder called {config.folder!r}")
        except imaplib.IMAP4.error as exc:
            self.close()
            raise MailError(f"Couldn't open the folder {config.folder!r}") from exc
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        imap, self._imap = self._imap, None
        if imap is None:
            return
        try:
            imap.logout()
        except (OSError, imaplib.IMAP4.error):
            pass

    def unseen(self, limit: int = MAX_PER_CHECK) -> Iterator[tuple[bytes, bytes]]:
        """The unread messages, oldest first, as (uid, raw bytes)."""
        assert self._imap is not None, "use Mailbox as a context manager"
        status, data = self._imap.uid("search", None, "UNSEEN")
        if status != "OK":
            raise MailError("Couldn't look for new mail")
        for uid in (data[0] or b"").split()[:limit]:
            status, parts = self._imap.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                log.warning("Skipped a message that couldn't be fetched (uid %s)", uid)
                continue
            yield uid, parts[0][1]

    def mark_seen(self, uid: bytes) -> None:
        assert self._imap is not None, "use Mailbox as a context manager"
        self._imap.uid("store", uid, "+FLAGS", "(\\Seen)")


def check_connection(config: MailboxConfig) -> None:
    """Opens the mailbox and closes it again. Raises MailError with something a person can act on."""
    with Mailbox(config):
        pass


def _login_hint(exc: Exception) -> str:
    text = str(exc).lower()
    if "application-specific" in text or "app password" in text or "credentials" in text or "auth" in text:
        return ("The mail server refused the sign-in. Most providers need an app password rather than your normal "
                "one, with two-factor turned on.")
    return f"The mail server refused the sign-in ({exc})"
