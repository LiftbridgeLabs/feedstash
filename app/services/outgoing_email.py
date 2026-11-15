"""Sending email: which SMTP settings apply, saving them, and the messages FeedStash sends (reset links, invites, a
test). Settings saved in Settings → Admin → Email win; otherwise the SMTP_* environment variables apply.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from app.clock import now
from app.crypto import SecretBox
from app.db import Database
from app.db.repositories import app_settings as app_settings_repo
from app.db.repositories import users as users_repo
from app.errors import InvalidInput
from app.mail import smtp
from app.mail.smtp import EmailSettings
from app.settings import Settings

log = logging.getLogger("reader.email")

PREFIX = "email."
SENT_PREFIX = "sent_email."  # not under PREFIX: these are counters, not settings
SENT_TODAY = "This server has sent all the email it can today. Try again tomorrow."


@dataclass(frozen=True, slots=True)
class EmailConfig:
    settings: EmailSettings
    source: str  # "app" (saved in Settings), "server" (environment variables) or "none"
    password_unreadable: bool = False  # saved, but encrypted with a different SECRET_KEY


def load(conn: sqlite3.Connection, settings: Settings, secrets: SecretBox) -> EmailConfig:
    saved = app_settings_repo.get_all(conn, PREFIX)
    if saved.get(PREFIX + "host"):
        stored = saved.get(PREFIX + "password", "")
        password = secrets.decrypt(stored) if stored else ""
        return EmailConfig(
            EmailSettings(
                host=saved[PREFIX + "host"], port=int(saved.get(PREFIX + "port") or 587),
                security=saved.get(PREFIX + "security") or "starttls", username=saved.get(PREFIX + "username", ""),
                password=password or "", from_address=saved.get(PREFIX + "from_address", ""),
                from_name=saved.get(PREFIX + "from_name") or "FeedStash",
            ),
            "app", password_unreadable=bool(stored) and password is None,
        )
    env = EmailSettings(
        host=settings.smtp_host, port=settings.smtp_port, security=settings.smtp_security,
        username=settings.smtp_username, password=settings.smtp_password.get_secret_value(),
        from_address=settings.smtp_from, from_name=settings.smtp_from_name or "FeedStash",
    )
    return EmailConfig(env, "server" if env.host else "none")


def save(
    conn: sqlite3.Connection, secrets: SecretBox, *, host: str, port: int, security: str, username: str,
    password: str | None, from_address: str, from_name: str,
) -> None:
    """Saves email settings in the app. `password=None` keeps the saved one; "" removes it."""
    host = host.strip()
    if not host:
        raise InvalidInput("Enter the SMTP server's address, like smtp.example.com")
    if security not in smtp.SECURITY:
        raise InvalidInput("Security is STARTTLS, SSL or none")
    if not 1 <= port <= 65535:
        raise InvalidInput("The port is a number from 1 to 65535")
    from_address = users_repo.valid_email(from_address)
    values = {
        PREFIX + "host": host, PREFIX + "port": str(port), PREFIX + "security": security,
        PREFIX + "username": username.strip(), PREFIX + "from_address": from_address,
        PREFIX + "from_name": " ".join(from_name.split()) or "FeedStash",
    }
    if password is not None:
        values[PREFIX + "password"] = secrets.encrypt(password) if password else ""
    app_settings_repo.set_many(conn, values)


def clear(conn: sqlite3.Connection) -> None:
    """Removes the settings saved in the app; the environment variables (if any) apply again."""
    conn.execute("DELETE FROM app_settings WHERE key LIKE ? || '%'", (PREFIX,))


def configured(db: Database, settings: Settings, secrets: SecretBox) -> bool:
    with db.transaction() as conn:
        return load(conn, settings, secrets).settings.ready


def _current(db: Database, settings: Settings, secrets: SecretBox) -> EmailSettings:
    with db.transaction() as conn:
        config = load(conn, settings, secrets).settings
    if not config.ready:
        raise smtp.SendError("Email isn't set up on this server.")
    return config


def _count(db: Database, settings: Settings) -> None:
    """Counts one email toward EMAIL_DAILY_LIMIT, or refuses it once today's are used up. Counted before it's
    sent, so a burst can't slip past, and one that then fails to send still counts."""
    if not settings.email_daily_limit:
        return
    key = SENT_PREFIX + datetime.fromtimestamp(now(), UTC).strftime("%Y-%m-%d")
    with db.transaction() as conn:
        app_settings_repo.forget_others(conn, SENT_PREFIX, key)
        if not app_settings_repo.count_up(conn, key, limit=settings.email_daily_limit):
            raise smtp.SendError(SENT_TODAY)


def send_test(db: Database, settings: Settings, secrets: SecretBox, *, to: str) -> None:
    config = _current(db, settings, secrets)
    _count(db, settings)
    smtp.send(config, smtp.message(
        config, to=to, subject="FeedStash can send email",
        text="This is a test from your FeedStash server. Email works: \"Forgot password?\" on the sign-in page "
             "can send reset links, and invites can be emailed.\n",
    ))


def send_reset(db: Database, settings: Settings, secrets: SecretBox, *, to: str, link: str) -> None:
    config = _current(db, settings, secrets)
    _count(db, settings)
    smtp.send(config, smtp.message(
        config, to=to, subject="Reset your FeedStash password",
        text=f"Someone asked to reset the password for {to} on FeedStash. If it was you, choose a new one here:\n\n"
             f"{link}\n\nThe link works once, for the next hour. If you didn't ask, ignore this email: your password "
             "stays as it is.\n",
    ))


def _tell(db: Database, settings: Settings, secrets: SecretBox, *, to: str, subject: str, text: str) -> None:
    """A notice about a change to an account. Sent only if this server can send email, and never an error for
    whoever made the change: it has happened either way."""
    try:
        with db.transaction() as conn:
            config = load(conn, settings, secrets).settings
        if not config.ready:
            return
        _count(db, settings)
        smtp.send(config, smtp.message(config, to=to, subject=subject, text=text))
    except smtp.SendError as exc:
        log.warning("Couldn't email a notice about an account change: %s", exc)


def tell_email_changed(db: Database, settings: Settings, secrets: SecretBox, *, old: str, new: str) -> None:
    """The old address hears where the account went (it's the one that matters if someone else did this); the new
    one hears that it works."""
    if old == new:
        return
    _tell(db, settings, secrets, to=old, subject="Your FeedStash email was changed",
          text=f"The email for your FeedStash account was changed from {old} to {new}. You now sign in with the "
               "new address, and password-reset links go there.\n\nIf you didn't do this, tell whoever runs your "
               "FeedStash server right away: someone else may have your password.\n")
    _tell(db, settings, secrets, to=new, subject="This is now your FeedStash email",
          text=f"Your FeedStash account now uses {new}. Sign in with it from now on; password-reset links come "
               "here too.\n")


def tell_password_changed(db: Database, settings: Settings, secrets: SecretBox, *, to: str) -> None:
    _tell(db, settings, secrets, to=to, subject="Your FeedStash password was changed",
          text=f"The password for {to} on FeedStash was just changed.\n\nIf you didn't do this, use \"Forgot "
               "password?\" on the sign-in page to set a new one, and tell whoever runs your FeedStash server.\n")


def send_invite(
    db: Database, settings: Settings, secrets: SecretBox, *, to: str, link: str, invited_by: str, expires: str,
) -> None:
    config = _current(db, settings, secrets)
    _count(db, settings)
    smtp.send(config, smtp.message(
        config, to=to, subject=f"{invited_by} invited you to FeedStash",
        text=f"{invited_by} invited you to their FeedStash server: your own feeds and saved links.\n\n"
             f"Make your account here (you choose your password):\n\n{link}\n\n"
             f"The link works once, until {expires}.\n",
    ))
