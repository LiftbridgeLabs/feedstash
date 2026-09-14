"""FastAPI dependencies shared by the routers."""

import asyncio
from collections.abc import Coroutine
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.db import Database
from app.db.models import User
from app.settings import Settings
from app.web.auth import session_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_user(request: Request) -> User:
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[Database, Depends(get_db)]
UserDep = Annotated[User, Depends(get_user)]


def run_in_background(request: Request, coroutine: Coroutine) -> None:
    """Starts work that outlives the request; the app cancels leftovers on shutdown."""
    tasks: set[asyncio.Task] = request.app.state.background_tasks
    task = asyncio.create_task(coroutine)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
