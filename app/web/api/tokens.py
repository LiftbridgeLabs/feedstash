"""API tokens for the extension, email worker and phone apps. Managed only from a signed-in web session."""

from urllib.parse import urlencode

import segno
from fastapi import APIRouter, Request, Response

from app.clock import now
from app.db.repositories import tokens as tokens_repo
from app.errors import InvalidInput
from app.web.deps import DatabaseDep, SessionUserDep, SettingsDep, api_token_id
from app.web.schemas import ConnectCode, ConnectCodeIn, ConnectCodeOut, NewTokenIn, NewTokenOut, TokenOut

router = APIRouter(prefix="/api")


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(user: SessionUserDep, db: DatabaseDep) -> list[TokenOut]:
    with db.transaction() as conn:
        return [TokenOut.from_token(token) for token in tokens_repo.list_for_user(conn, user.id)]


@router.post("/tokens", status_code=201, response_model=NewTokenOut)
def create_token(body: NewTokenIn, user: SessionUserDep, db: DatabaseDep) -> NewTokenOut:
    with db.transaction() as conn:
        token, secret = tokens_repo.create(conn, user.id, body.clientName, now=now())
    return NewTokenOut(id=token.id, token=secret, clientName=token.client_name)


def connect_url(server: str, token: str) -> str:
    """What the QR code holds: this server's /connect page with the server and token after the #. The Camera app
    opens it (it won't open feedstash:// links), the page hands off to the app, and the app's own scanner reads it
    directly. The part after # never reaches a server."""
    return f"{server.rstrip('/')}/connect#" + urlencode({"server": server, "token": token})


def qr_svg(text: str) -> str:
    # Black on white whatever the theme, with a quiet zone, so phone cameras read it on dark screens too.
    # omitsize: a viewBox instead of fixed pixels, so the page can size it without cropping.
    return segno.make(text, error="m").svg_inline(border=3, dark="#000", light="#fff", omitsize=True)


@router.post("/tokens/connect", status_code=201, response_model=ConnectCodeOut)
def create_connect_code(
    body: ConnectCodeIn, request: Request, user: SessionUserDep, db: DatabaseDep, settings: SettingsDep
) -> ConnectCodeOut:
    """A new token for the phone or iPad app, as a QR code the app can scan to connect without typing."""
    with db.transaction() as conn:
        token, secret = tokens_repo.create(conn, user.id, body.clientName.strip() or "Phone or iPad", now=now())
    current = settings.base_url_for(str(request.base_url))
    servers = [current] + [url for url in settings.base_urls if url != current]
    codes = [ConnectCode(server=server, url=connect_url(server, secret), svg=qr_svg(connect_url(server, secret)))
             for server in servers]
    return ConnectCodeOut(id=token.id, token=secret, clientName=token.client_name, codes=codes)


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: int, request: Request, user: SessionUserDep, db: DatabaseDep) -> Response:
    if api_token_id(request) == token_id:
        raise InvalidInput("Cannot revoke the token you are currently using")
    with db.transaction() as conn:
        tokens_repo.delete(conn, user.id, token_id)
    return Response(status_code=204)
