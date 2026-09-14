"""Maps domain errors and request validation errors to JSON responses with a readable `detail`."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import Conflict, InvalidInput, NotFound, ReaderError

STATUS_CODES: dict[type[ReaderError], int] = {InvalidInput: 400, NotFound: 404, Conflict: 409}


def install(app: FastAPI) -> None:
    @app.exception_handler(ReaderError)
    async def reader_error(request: Request, exc: ReaderError) -> JSONResponse:
        status = next((code for kind, code in STATUS_CODES.items() if isinstance(exc, kind)), 400)
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path"))
        message = first.get("msg", "Invalid request")
        return JSONResponse({"detail": f"{field}: {message}" if field else message}, status_code=400)
