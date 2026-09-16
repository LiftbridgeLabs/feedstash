"""FastAPI dependencies shared by the routers."""

import asyncio
from collections.abc import Coroutine
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.crypto import SecretBox
from app.db import Database
from app.db.models import User
from app.images import ImageStore
from app.settings import Settings
from app.web.auth import bearer_token, session_user, token_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_images(request: Request) -> ImageStore:
    return request.app.state.images


def get_secrets(request: Request) -> SecretBox:
    return request.app.state.secrets


def get_user(request: Request) -> User:
    """The web session's user, or the owner of the API token the request carries."""
    token = bearer_token(request)
    if token is not None:
        user = token_user(request, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[Database, Depends(get_db)]
ImagesDep = Annotated[ImageStore, Depends(get_images)]
SecretsDep = Annotated[SecretBox, Depends(get_secrets)]
UserDep = Annotated[User, Depends(get_user)]


def api_client_name(request: Request) -> str | None:
    """The client name of the API token used for this request, if any (e.g. "extension")."""
    match = getattr(request.state, "api_token", None)
    return match.client_name if match else None


def api_token_id(request: Request) -> int | None:
    match = getattr(request.state, "api_token", None)
    return match.token_id if match else None


def run_in_background(request: Request, coroutine: Coroutine) -> None:
    """Starts work that outlives the request; the app cancels leftovers on shutdown."""
    tasks: set[asyncio.Task] = request.app.state.background_tasks
    task = asyncio.create_task(coroutine)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
