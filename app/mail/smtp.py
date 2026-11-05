"""Sending email through an SMTP server (no database): password-reset links, invites, a test message.

Blocking (smtplib); callers run it in a thread. Errors come back as SendError with a message for the admin who set
email up, never with the password in it.
"""

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

SECURITY = ("starttls", "ssl", "none")
TIMEOUT_SECONDS = 20


class SendError(Exception):
    """An email couldn't be sent. The message is meant to be shown to an admin."""


@dataclass(frozen=True, slots=True)
class EmailSettings:
    host: str
    port: int
    security: str  # starttls (usually port 587), ssl (465) or none (25, a server on your own network)
    username: str
    password: str
    from_address: str
    from_name: str = "FeedStash"

    @property
    def ready(self) -> bool:
        return bool(self.host and self.from_address)


def message(settings: EmailSettings, *, to: str, subject: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.from_name, settings.from_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.from_address.rpartition("@")[2] or None)
    msg.set_content(text)
    return msg


def send(settings: EmailSettings, msg: EmailMessage) -> None:
    host = f"{settings.host}:{settings.port}"
    try:
        if settings.security == "ssl":
            client = smtplib.SMTP_SSL(settings.host, settings.port, timeout=TIMEOUT_SECONDS,
                                      context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(settings.host, settings.port, timeout=TIMEOUT_SECONDS)
        with client:
            client.ehlo()
            if settings.security == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if settings.username:
                try:
                    client.login(settings.username, settings.password)
                except UnicodeError:
                    raise SendError(f"{host} can't be sent this username or password: it has characters SMTP "
                                    "logins don't allow.") from None
            client.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(f"{host} didn't accept the username and password ({exc.smtp_code}).") from None
    except smtplib.SMTPNotSupportedError:
        raise SendError(f"{host} doesn't offer STARTTLS. Try SSL (usually port 465).") from None
    except smtplib.SMTPRecipientsRefused:
        raise SendError(f"{host} refused to send to {msg['To']}.") from None
    except smtplib.SMTPSenderRefused as exc:
        raise SendError(f"{host} won't send from {settings.from_address} ({exc.smtp_code}). Use an address "
                        "your email service lets you send from.") from None
    except smtplib.SMTPException as exc:
        raise SendError(f"{host} said: {exc}") from None
    except ssl.SSLError as exc:
        raise SendError(f"Couldn't make a secure connection to {host} ({exc.reason or exc}). Check the security "
                        "setting: STARTTLS usually goes with port 587, SSL with 465.") from None
    except (TimeoutError, socket.timeout):
        raise SendError(f"{host} didn't answer in time.") from None
    except OSError as exc:
        raise SendError(f"Couldn't reach {host}: {exc.strerror or exc}.") from None
