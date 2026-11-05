"""A tiny SMTP server for tests: accepts every message (no TLS) and keeps it, so tests can read what FeedStash
sent. `require_auth` makes it insist on AUTH PLAIN/LOGIN with one username and password."""

import base64
import email
import socketserver
import threading
import time
from email.message import Message


class FakeSMTP:
    def __init__(self, *, require_auth: tuple[str, str] | None = None):
        self.messages: list[Message] = []
        self.require_auth = require_auth
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, line: str) -> None:
                self.wfile.write((line + "\r\n").encode())

            def handle(self) -> None:
                self.reply("220 fake ESMTP")
                authed = fake.require_auth is None
                while line := self.rfile.readline().decode(errors="replace").rstrip("\r\n"):
                    verb = line.split(" ", 1)[0].upper()
                    if verb in ("EHLO", "HELO"):
                        self.reply("250-fake")
                        self.reply("250 AUTH PLAIN LOGIN")
                    elif verb == "AUTH":
                        authed = self.auth(line)
                        self.reply("235 ok" if authed else "535 bad credentials")
                    elif verb in ("MAIL", "RCPT") and not authed:
                        self.reply("530 authentication required")
                    elif verb in ("MAIL", "RCPT", "RSET", "NOOP"):
                        self.reply("250 ok")
                    elif verb == "DATA":
                        self.reply("354 go ahead")
                        data = []
                        while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                            data.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                        fake.messages.append(email.message_from_bytes(b"".join(data)))
                        self.reply("250 queued")
                    elif verb == "QUIT":
                        self.reply("221 bye")
                        return
                    else:
                        self.reply("502 not implemented")

            def auth(self, line: str) -> bool:
                parts = line.split()
                if parts[1].upper() == "PLAIN":
                    raw = parts[2] if len(parts) > 2 else (self.reply("334 ") or self.rfile.readline().strip().decode())
                    _, user, password = base64.b64decode(raw).decode().split("\0")
                else:  # LOGIN
                    self.reply("334 VXNlcm5hbWU6")
                    user = base64.b64decode(self.rfile.readline().strip()).decode()
                    self.reply("334 UGFzc3dvcmQ6")
                    password = base64.b64decode(self.rfile.readline().strip()).decode()
                return fake.require_auth == (user, password)

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def wait_for(self, count: int = 1, timeout: float = 10) -> list[Message]:
        deadline = time.monotonic() + timeout
        while len(self.messages) < count and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.messages

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def body(msg: Message) -> str:
    return msg.get_payload(decode=True).decode()
