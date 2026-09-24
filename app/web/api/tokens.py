"""API tokens for the extension, email worker and phone apps. Managed only from a signed-in web session."""

from fastapi import APIRouter, Request, Response

from app.clock import now
from app.db.repositories import tokens as tokens_repo
from app.errors import InvalidInput
from app.web.deps import DatabaseDep, SessionUserDep, api_token_id
from app.web.schemas import NewTokenIn, NewTokenOut, TokenOut

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


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: int, request: Request, user: SessionUserDep, db: DatabaseDep) -> Response:
    if api_token_id(request) == token_id:
        raise InvalidInput("Cannot revoke the token you are currently using")
    with db.transaction() as conn:
        tokens_repo.delete(conn, user.id, token_id)
    return Response(status_code=204)
