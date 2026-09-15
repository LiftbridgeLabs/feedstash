from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "reader"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src * data: blob:; media-src *; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'self'; "
    "form-action 'self' https://accounts.google.com; frame-ancestors 'none'"
)


class SecureCookieOverHttps:
    """Marks one cookie Secure on responses to https requests only. For servers reached over both http (at home)
    and https (through a reverse proxy), where a cookie that is always Secure would break the http address."""

    def __init__(self, app, cookie_name: str):
        self.app = app
        self.prefix = f"{cookie_name}=".encode()

    def _secured(self, header: bytes) -> bytes:
        if not header.startswith(self.prefix):
            return header
        attributes = [part.strip().lower() for part in header.split(b";")[1:]]
        return header if b"secure" in attributes else header + b"; secure"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("scheme") != "https":
            await self.app(scope, receive, send)
            return

        async def send_with_secure_cookie(message):
            if message["type"] == "http.response.start":
                headers = [
                    (name, self._secured(value) if name.lower() == b"set-cookie" else value)
                    for name, value in message.get("headers", [])
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_secure_cookie)


def _sends_bearer_token(request: Request) -> bool:
    return request.headers.get("authorization", "").lower().startswith("bearer ")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # State-changing requests must come from the app's own JavaScript: cross-site forms can't send a
        # custom header, and the session cookie is SameSite=Lax. Requests with a bearer token are exempt:
        # browsers never attach those on their own, so they can't be forged from another site.
        if (
            request.method not in SAFE_METHODS
            and not _sends_bearer_token(request)
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            message = "Missing CSRF header"
            return JSONResponse({"detail": message, "error": message}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response
