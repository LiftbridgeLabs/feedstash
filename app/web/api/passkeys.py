"""Passkeys in Settings → You: the list, adding one on this device, renaming and removing. Signing in with one is in
app/web/auth.py."""

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.services import passkeys
from app.web.auth import PASSWORD_CHECKS
from app.web.deps import DatabaseDep, SessionUserDep, SettingsDep
from app.web.schemas import OkOut, PasskeyAddIn, PasskeyOptionsOut, PasskeyOut, PasskeyRenameIn, PasskeysOut

router = APIRouter(prefix="/api/account/passkeys")

SESSION_NEW_PASSKEY_KEY = "passkey_new"  # an add in progress: {challenge, handle, user, at}


def _out(passkey) -> PasskeyOut:
    return PasskeyOut(id=passkey.id, name=passkey.name, created_at=passkey.created_at, last_used_at=passkey.last_used_at)


@router.get("", response_model=PasskeysOut)
def list_passkeys(request: Request, user: SessionUserDep, db: DatabaseDep, settings: SettingsDep) -> PasskeysOut:
    party = passkeys.relying_party(settings, str(request.base_url))
    return PasskeysOut(
        available=party is not None, reason="" if party else passkeys.unavailable_reason(settings),
        has_password=user.has_password, passkeys=[_out(p) for p in passkeys.list_for(db, user.id)],
    )


@router.post("/options", response_model=PasskeyOptionsOut)
def add_options(request: Request, user: SessionUserDep, db: DatabaseDep, settings: SettingsDep) -> PasskeyOptionsOut:
    """Asked for when the Add a passkey dialog opens, so its button can go straight to the device."""
    party = passkeys.relying_party(settings, str(request.base_url))
    if party is None:
        raise HTTPException(status_code=400, detail=passkeys.unavailable_reason(settings))
    options, challenge, handle = passkeys.registration_options(db, user, party)
    request.session[SESSION_NEW_PASSKEY_KEY] = {"challenge": challenge, "handle": handle, "user": user.id, "at": now()}
    return PasskeyOptionsOut(options=options)


@router.post("", response_model=PasskeyOut, status_code=201)
async def add_passkey(
    body: PasskeyAddIn, request: Request, user: SessionUserDep, db: DatabaseDep, settings: SettingsDep,
) -> PasskeyOut:
    party = passkeys.relying_party(settings, str(request.base_url))
    pending = request.session.pop(SESSION_NEW_PASSKEY_KEY, None)  # used once, right or wrong
    if party is None:
        raise HTTPException(status_code=400, detail=passkeys.unavailable_reason(settings))
    if (not isinstance(pending, dict) or pending.get("user") != user.id
            or now() - int(pending.get("at", 0)) > passkeys.CEREMONY_SECONDS):
        raise HTTPException(status_code=400, detail="That took too long. Try adding the passkey again.")
    async with PASSWORD_CHECKS:
        added = await run_in_threadpool(
            passkeys.register, db, user, party, credential=body.credential, challenge=pending["challenge"],
            handle=pending["handle"], name=body.name, password=body.password, now=now(),
        )
    return _out(added)


@router.patch("/{passkey_id}", response_model=OkOut)
def rename_passkey(passkey_id: int, body: PasskeyRenameIn, user: SessionUserDep, db: DatabaseDep) -> OkOut:
    passkeys.rename(db, user.id, passkey_id, body.name)
    return OkOut()


@router.delete("/{passkey_id}", response_model=OkOut)
def remove_passkey(passkey_id: int, user: SessionUserDep, db: DatabaseDep) -> OkOut:
    """Removing one needs no password: it only takes a way in away. The device keeps offering it until it's deleted
    there too; signing in with it then says it was removed."""
    passkeys.remove(db, user.id, passkey_id)
    return OkOut()
