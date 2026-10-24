"""Private in-workload BiDi reads; no Kubernetes or externally exposed debugger."""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from typing import Any

import websockets.sync.client


class NativeReplyError(RuntimeError):
    """Correlated protocol rejection; never expose native messages/page data."""
    def __init__(self, code):
        self.native_code = code if code in {
            "invalid argument", "unsupported operation", "no such frame",
            "no such user context", "unknown error"} else "unknown error"
        super().__init__("private Firefox command rejected")


class CdpSession:
    protocol = "bidi"

    def __init__(self, *, websocket_url: str | None = None):
        if websocket_url is None and os.environ.get('FIREFOX_CONTROL_PROTOCOL') == 'firefox-windows-v3':
            raise RuntimeError('FIREFOX_RESIDENT_SESSION_REQUIRED: attach the bridge-owned session; session.new is disabled')
        self.next_id = 0
        self.pending = None
        self.lock = threading.RLock()
        self.owns_session = websocket_url is None
        self.ws = websockets.sync.client.connect(
            websocket_url or "ws://127.0.0.1:9222/session", open_timeout=5, close_timeout=2,
            max_size=2_000_000, compression=None, proxy=None,
        )
        try:
            if self.owns_session:
                self._bidi("session.new", {"capabilities": {"alwaysMatch": {}}})
        except BaseException:
            self.ws.close()
            raise

    def _bidi(self, method: str, params: dict | None = None, *, on_reply=None) -> dict:
        with self.lock:
            return self._exchange(method, params, on_reply=on_reply)

    def _exchange(self, method: str, params: dict | None = None, *, on_reply=None) -> dict:
        if self.ws is None:
            raise NativeNotSent("private Firefox observer is closed")
        # One outstanding creation per observer. Drain, never resend, before
        # accepting any subsequent command on this transport.
        self.drain_pending()
        self.next_id += 1
        if on_reply is not None:
            self.pending = {"id": self.next_id, "receipt": on_reply}
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params or {}}))
        return self._receive(self.next_id, on_reply)

    def drain_pending(self):
        with self.lock:
            if self.pending is not None:
                return self._receive(self.pending["id"], self.pending["receipt"])

    def _receive(self, command_id, on_reply):
        if self.ws is None:
            raise RuntimeError("private Firefox pending observer is closed")
        deadline = time.monotonic() + 10
        while True:
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise TimeoutError("private Firefox observation timed out")
                reply = json.loads(self.ws.recv(timeout=remaining))
            except TimeoutError:
                if on_reply is not None:
                    raise NativeReplyPending(command_id) from None
                raise
            if reply.get("id") == command_id:
                # The resident owner fsyncs creation receipts before returning
                # to its caller. HTTP disconnects do not cancel this commit.
                if on_reply is not None:
                    on_reply(reply)
                    self.pending = None  # Only after durable receipt commit.
                if reply.get("type") == "error" or "error" in reply:
                    raise NativeReplyError(reply.get("error"))
                return reply.get("result") or {}

    def _bidi_contexts(self) -> list[dict]:
        return [item for item in self._bidi("browsingContext.getTree").get("contexts", []) if isinstance(item, dict)]

    @staticmethod
    def _bidi_value(value: dict) -> Any:
        raw = value.get("value")
        if value.get("type") == "array" and isinstance(raw, list):
            return [CdpSession._bidi_value(item) for item in raw]
        if value.get("type") == "object" and isinstance(raw, list):
            return {str(key.get("value") if isinstance(key, dict) else key): CdpSession._bidi_value(item) for key, item in raw}
        return raw

    def close(self):
        # End the controller session, never the Firefox process or its tabs.
        with self.lock:
            if self.ws is None:
                return
            try:
                if self.owns_session:
                    with contextlib.suppress(Exception):
                        self._bidi("session.end")
            finally:
                self.ws.close()
                self.ws = None


class NativeNotSent(RuntimeError):
    native_outcome = "not_started"


class NativeReplyPending(TimeoutError):
    native_outcome = "reply_pending"

    def __init__(self, command_id):
        self.command_id = command_id
        super().__init__("private Firefox creation reply pending; do not resend")


def _with_browser(callback):
    browser = CdpSession()
    try:
        return callback(browser)
    finally:
        browser.close()
