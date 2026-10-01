"""The mailbox an account connects, so forwarding an email saves it to the stash.

Managed from the web app only (SessionUserDep): FeedStash signs in to the mailbox with its saved password, so an API
token that could change where it signs in could collect that password.
"""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.db.repositories import mail as mail_repo
from app.errors import InvalidInput
from app.mail.imap import MailError, check_connection
from app.services.mail import check_account, mailbox_config
from app.web.deps import DatabaseDep, ImagesDep, SecretsDep, SessionUserDep, SettingsDep
from app.web.schemas import MailCheckOut, MailIn, MailOut, MailTestOut, OkOut

router = APIRouter(prefix="/api/mail")

DEFAULT_PORT = 993


@router.get("", response_model=MailOut)
def get_mailbox(user: SessionUserDep, db: DatabaseDep, settings: SettingsDep) -> MailOut:
    with db.transaction() as conn:
        account = mail_repo.for_user(conn, user.id)
    return MailOut.from_account(account, poll_minutes=settings.mail_poll_minutes)


@router.put("", response_model=MailOut)
async def connect_mailbox(
    body: MailIn, request: Request, user: SessionUserDep, db: DatabaseDep, secrets: SecretsDep, settings: SettingsDep
) -> MailOut:
    """Connects a mailbox, or changes the one already connected. Send no password to keep the saved one."""
    host = body.host.strip()
    username = body.username.strip()
    if not host or not username:
        raise InvalidInput("A mailbox needs a server and a username")

    def save():
        with db.transaction() as conn:
            current = mail_repo.for_user(conn, user.id)
            port = body.port or DEFAULT_PORT
            # The saved password only goes to the server it was entered for: a new server, port or username needs it
            # typed again.
            same_server = current is not None and (current.host, current.port, current.username) == (host, port, username)
            password = secrets.encrypt(body.password) if body.password else (current.password if same_server else "")
            if not password:
                if current is not None and not same_server:
                    raise InvalidInput("Enter the mailbox password again when you change the server or username")
                raise InvalidInput("Enter the mailbox password (most providers want an app password)")
            return mail_repo.save(
                conn, user.id, host=host, port=port, username=username, password=password,
                folder=(body.folder or "INBOX").strip() or "INBOX",
                allowed_senders=[s.strip().lower() for s in body.allowedSenders if s.strip()],
                enabled=body.enabled, now=now(),
            )

    account = await run_in_threadpool(save)
    # Starting it here (on the event loop) is why this endpoint is async: the checker stops itself when the last
    # mailbox goes, so connecting one has to wake it again.
    request.app.state.mail_worker.start()
    return MailOut.from_account(account, poll_minutes=settings.mail_poll_minutes)


@router.post("/test", response_model=MailTestOut)
async def test_mailbox(user: SessionUserDep, db: DatabaseDep, secrets: SecretsDep) -> MailTestOut:
    """Signs in to the connected mailbox and out again, to say plainly whether it works."""
    def prepare():
        with db.transaction() as conn:
            return mailbox_config(mail_repo.get(conn, user.id), secrets)

    try:
        config = await run_in_threadpool(prepare)
        await run_in_threadpool(check_connection, config)
    except MailError as exc:
        return MailTestOut(ok=False, error=str(exc))
    return MailTestOut(ok=True, error=None)


@router.post("/check", response_model=MailCheckOut)
async def check_mailbox(user: SessionUserDep, db: DatabaseDep, images: ImagesDep, secrets: SecretsDep) -> MailCheckOut:
    """Checks the mailbox now instead of waiting for the next round."""
    def run():
        with db.transaction() as conn:
            account = mail_repo.get(conn, user.id)
        return check_account(db, images, secrets, account)

    try:
        return MailCheckOut(saved=await run_in_threadpool(run), error=None)
    except MailError as exc:
        return MailCheckOut(saved=0, error=str(exc))


@router.delete("", response_model=OkOut)
def disconnect_mailbox(user: SessionUserDep, db: DatabaseDep) -> OkOut:
    with db.transaction() as conn:
        mail_repo.delete(conn, user.id)
    return OkOut()
