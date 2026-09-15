"""Maps errors to JSON responses carrying a readable message.

The message is sent as `detail` (read by this app's UI) and as `error` (read by the extension, email worker and phone apps).
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import Conflict, InvalidInput, NotFound, ReaderError

STATUS_CODES: dict[type[ReaderError], int] = {InvalidInput: 400, NotFound: 404, Conflict: 409}


def error_response(message: str, status_code: int, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": message, "error": message}, status_code=status_code, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ReaderError)
    async def reader_error(request: Request, exc: ReaderError) -> JSONResponse:
        status = next((code for kind, code in STATUS_CODES.items() if isinstance(exc, kind)), 400)
        return error_response(str(exc), status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(str(exc.detail), exc.status_code, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path"))
        message = first.get("msg", "Invalid request")
        return error_response(f"{field}: {message}" if field else message, 400)
