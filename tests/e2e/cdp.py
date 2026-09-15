"""A tiny synchronous Chrome DevTools Protocol client, enough to drive a headless Edge/Chrome tab."""

import json
import time
from contextlib import ExitStack

from websockets.sync.client import connect

IGNORED_ERROR_SOURCES = ("favicon", "gstatic", "example.com")


class Page:
    def __init__(self, ws_url: str):
        self._resources = ExitStack()
        self.ws = self._resources.enter_context(connect(ws_url, max_size=None))
        self.next_id = 0
        self.errors: list[str] = []
        for method in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.send(method)

    def close(self) -> None:
        self._resources.close()

    def _on_event(self, message: dict) -> None:
        method, params = message.get("method"), message.get("params", {})
        if method == "Runtime.exceptionThrown":
            details = params["exceptionDetails"]
            self.errors.append(details.get("exception", {}).get("description") or details.get("text"))
        elif method == "Log.entryAdded" and params["entry"]["level"] == "error":
            entry = params["entry"]
            if not any(source in (entry.get("url") or "") for source in IGNORED_ERROR_SOURCES):
                self.errors.append(f"{entry['text']} {entry.get('url') or ''}")

    def send(self, method: str, **params) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv(timeout=30))
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self._on_event(message)

    def pump(self, seconds: float) -> None:
        """Waits while still collecting console errors."""
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                self._on_event(json.loads(self.ws.recv(timeout=remaining)))
            except TimeoutError:
                return

    def js(self, expression: str):
        result = self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS error in {expression[:80]!r}: {result['exceptionDetails']}")
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 10) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(expression):
                return True
            self.pump(0.2)
        return False

    def goto(self, url: str) -> None:
        self.send("Page.navigate", url=url)

    def press(self, key: str) -> None:
        # Printable keys carry text; named keys like "Escape" must not.
        self.send("Input.dispatchKeyEvent", type="keyDown", key=key, **({"text": key} if len(key) == 1 else {}))
        self.send("Input.dispatchKeyEvent", type="keyUp", key=key)

    def viewport(self, width: int, height: int, mobile: bool = False) -> None:
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=2 if mobile else 1, mobile=mobile)
