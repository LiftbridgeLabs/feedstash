"""A minimal OpenID Connect provider for tests: discovery, an authorize endpoint that approves at once, token,
JWKS and userinfo. Set `claims` before starting a sign-in; they end up in the signed ID token."""

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from authlib.jose import JsonWebKey, jwt

CLIENT_ID = "feedstash-test"
CLIENT_SECRET = "test-client-secret"
KEY_ID = "test-key"


class FakeOidcProvider:
    def __init__(self, port: int):
        self.issuer = f"http://127.0.0.1:{port}"
        self.claims: dict = {}
        self._key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        self._grants: dict[str, dict] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())

    def start(self) -> None:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _metadata(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "userinfo_endpoint": f"{self.issuer}/userinfo",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    def _id_token(self, grant: dict) -> str:
        issued = int(time.time())
        claims = {"iss": self.issuer, "aud": CLIENT_ID, "iat": issued, "exp": issued + 300, **grant["claims"]}
        if grant["nonce"]:
            claims["nonce"] = grant["nonce"]
        token = jwt.encode({"alg": "RS256", "kid": KEY_ID}, claims, self._key)
        return token.decode() if isinstance(token, bytes) else token

    def _handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, body: dict, status: int = 200) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlparse(self.path)
                query = {key: values[0] for key, values in parse_qs(url.query).items()}
                if url.path == "/.well-known/openid-configuration":
                    self._json(provider._metadata())
                elif url.path == "/jwks":
                    public = provider._key.as_dict(is_private=False)
                    self._json({"keys": [{**public, "kid": KEY_ID, "use": "sig", "alg": "RS256"}]})
                elif url.path == "/authorize":
                    code = secrets.token_urlsafe(16)
                    provider._grants[code] = {"nonce": query.get("nonce"), "claims": dict(provider.claims)}
                    self.send_response(302)
                    self.send_header("Location", f"{query['redirect_uri']}?{urlencode({'code': code, 'state': query['state']})}")
                    self.end_headers()
                elif url.path == "/userinfo":
                    self._json(dict(provider.claims))
                else:
                    self._json({"error": "not_found"}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                form = {key: values[0] for key, values in parse_qs(self.rfile.read(length).decode()).items()}
                grant = provider._grants.pop(form.get("code", ""), None)
                if urlparse(self.path).path != "/token" or grant is None:
                    self._json({"error": "invalid_grant"}, 400)
                    return
                self._json({
                    "access_token": secrets.token_urlsafe(16), "token_type": "Bearer", "expires_in": 300,
                    "id_token": provider._id_token(grant),
                })

        return Handler
