"""For admins: how this server sends email (Settings → Admin → Email), and a test message."""

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.db.models import User
from app.mail.smtp import SendError
from app.services import outgoing_email
from app.web.deps import DatabaseDep, SecretsDep, SessionUserDep, SettingsDep, not_managed
from app.web.schemas import EmailSettingsIn, EmailSettingsOut, EmailTestIn, OkOut

router = APIRouter(prefix="/api/admin/email", dependencies=[Depends(not_managed)])


def _admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can change how the server sends email")


def _out(config: outgoing_email.EmailConfig) -> EmailSettingsOut:
    s = config.settings
    return EmailSettingsOut(
        source=config.source, ready=s.ready, host=s.host, port=s.port, security=s.security, username=s.username,
        has_password=bool(s.password), password_unreadable=config.password_unreadable,
        from_address=s.from_address, from_name=s.from_name,
    )


@router.get("", response_model=EmailSettingsOut)
def get_settings(user: SessionUserDep, db: DatabaseDep, settings: SettingsDep, secrets: SecretsDep) -> EmailSettingsOut:
    _admin(user)
    with db.transaction() as conn:
        return _out(outgoing_email.load(conn, settings, secrets))


@router.put("", response_model=EmailSettingsOut)
def put_settings(
    body: EmailSettingsIn, user: SessionUserDep, db: DatabaseDep, settings: SettingsDep, secrets: SecretsDep,
) -> EmailSettingsOut:
    _admin(user)
    with db.transaction() as conn:
        outgoing_email.save(conn, secrets, **body.model_dump())
        return _out(outgoing_email.load(conn, settings, secrets))


@router.delete("", response_model=EmailSettingsOut)
def delete_settings(user: SessionUserDep, db: DatabaseDep, settings: SettingsDep, secrets: SecretsDep) -> EmailSettingsOut:
    """Forgets the settings saved here; the server's SMTP_* settings, if any, apply again."""
    _admin(user)
    with db.transaction() as conn:
        outgoing_email.clear(conn)
        return _out(outgoing_email.load(conn, settings, secrets))


@router.post("/test", response_model=OkOut)
async def send_test(
    body: EmailTestIn, user: SessionUserDep, db: DatabaseDep, settings: SettingsDep, secrets: SecretsDep,
) -> OkOut:
    _admin(user)
    to = (body.to or "").strip() or user.email
    try:
        await run_in_threadpool(outgoing_email.send_test, db, settings, secrets, to=to)
    except SendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return OkOut()
