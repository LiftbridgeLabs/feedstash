"""Two-step sign-in in Settings → You: turn it on with an authenticator app, new recovery codes, turn it off. And
for admins, turning it off for someone who lost their phone and their recovery codes."""

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.clock import now
from app.services import two_step
from app.web.api.accounts import AdminDep
from app.web.api.tokens import qr_svg
from app.web.auth import PASSWORD_CHECKS, start_session
from app.web.deps import DatabaseDep, SecretsDep, SessionUserDep
from app.web.schemas import (
    OkOut, RecoveryCodesOut, TwoStepConfirmIn, TwoStepOut, TwoStepSetupOut, TwoStepStartIn,
)

router = APIRouter(prefix="/api")


@router.get("/account/two-step", response_model=TwoStepOut)
def get_status(user: SessionUserDep, db: DatabaseDep) -> TwoStepOut:
    found = two_step.status(db, user.id)
    return TwoStepOut(enabled=found.enabled, recovery_codes_left=found.recovery_codes_left, available=user.has_password)


@router.post("/account/two-step/start", response_model=TwoStepSetupOut)
async def start(body: TwoStepStartIn, user: SessionUserDep, db: DatabaseDep, secrets: SecretsDep) -> TwoStepSetupOut:
    """A new secret for the app, after the password is checked again. Nothing changes until /confirm."""
    async with PASSWORD_CHECKS:
        secret, uri = await run_in_threadpool(two_step.begin, db, secrets, user, password=body.password, now=now())
    return TwoStepSetupOut(secret=secret, uri=uri, svg=qr_svg(uri))


@router.post("/account/two-step/confirm", response_model=RecoveryCodesOut)
async def confirm(
    body: TwoStepConfirmIn, request: Request, user: SessionUserDep, db: DatabaseDep, secrets: SecretsDep,
) -> RecoveryCodesOut:
    """Turns it on with a first code from the app. Other browsers are signed out; this one stays in."""
    codes = await run_in_threadpool(two_step.confirm, db, secrets, user, code=body.code, now=now())
    await start_session(request, user.id)
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/account/two-step/recovery-codes", response_model=RecoveryCodesOut)
async def new_codes(body: TwoStepStartIn, user: SessionUserDep, db: DatabaseDep) -> RecoveryCodesOut:
    """Ten new recovery codes; the old ones stop working."""
    async with PASSWORD_CHECKS:
        codes = await run_in_threadpool(two_step.new_recovery_codes, db, user, password=body.password)
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/account/two-step/off", response_model=OkOut)
async def turn_off(body: TwoStepStartIn, user: SessionUserDep, db: DatabaseDep) -> OkOut:
    async with PASSWORD_CHECKS:
        await run_in_threadpool(two_step.turn_off, db, user, password=body.password)
    return OkOut()


@router.post("/accounts/{user_id}/two-step/off", response_model=OkOut)
def turn_off_for(user_id: int, admin: AdminDep, db: DatabaseDep) -> OkOut:
    """An admin turning it off for someone else. They sign in with just their password until they turn it on again."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Turn off your own two-step sign-in in Settings → You")
    if not two_step.turn_off_for(db, user_id):
        raise HTTPException(status_code=404, detail="Two-step sign-in isn't on for that account")
    return OkOut()
