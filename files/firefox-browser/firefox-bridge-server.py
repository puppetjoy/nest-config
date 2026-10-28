#!/usr/bin/env python3
"""Authenticated fixed-function HTTP bridge for the owner-visible Firefox.

Contour terminates supervised TLS. Only this guarded API is routed, never the
private WebDriver/BiDi listeners. Disconnects never cancel/replay UI actions.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

MAX_REQUEST = 32_768
MAX_RESPONSE = 8_000_000
API_PATH = "/_nest/bridge/v1"
ROOT = Path(__file__).resolve().parent
TOKEN_PATH = Path(os.environ.get("FIREFOX_BRIDGE_TOKEN_FILE", "/run/nest-firefox-bridge/token"))
LOCK_PATH = Path(os.environ.get("FIREFOX_BRIDGE_LOCK", "/tmp/nest-firefox/endpoint.lock"))
FIELDS = {
    "status": set(), "diagnostics": set(), "snapshot": set(), "screenshot": set(),
    "query": {"expression", "cursor"}, "wait": {"max_wait_seconds"},
    "checkout_readback": {"safe_item_nickname", "max_wait_seconds"},
    "tabs": {"action", "workflow_id", "lease_seconds"},
    "navigate": {"url", "workflow_id", "lease_seconds", "max_wait_seconds"},
    "scroll": {"workflow_id", "direction", "amount"},
    "click": {"workflow_id", "locator", "coordinate", "action_key", "max_wait_seconds"},
    "type": {"workflow_id", "locator", "coordinate", "action_key", "text"},
    "selector_action": {"workflow_id", "operation", "selector", "expected_url", "expected_generation", "expected_tab", "action_key", "text", "max_wait_seconds", "mode"},
    "window_lifecycle": {"action", "scope", "terminal_event_id", "terminal_status"},
}
for _command in FIELDS:
    FIELDS[_command].add("scope")


def validate(envelope):
    if not isinstance(envelope, dict) or set(envelope) != {"command", "payload"}:
        raise ValueError("expected a fixed command and payload only")
    command, payload = envelope["command"], envelope["payload"]
    if not isinstance(command, str) or command not in FIELDS or not isinstance(payload, dict) or set(payload) - FIELDS[command]:
        raise ValueError("unsupported command or payload fields")
    if any(isinstance(value, str) and len(value) > 4096 for value in payload.values()):
        raise ValueError("payload string exceeds the input budget")
    return command, payload


def worker():
    command, payload = validate(json.load(sys.stdin))
    if "scope" in payload or command == "window_lifecycle":
        raise ValueError("scoped windows require the resident window controller; no global fallback")
    spec = importlib.util.spec_from_file_location("firefox_ui_bridge", ROOT / "firefox-ui-bridge.py")
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    if command == "query":
        import secure_browser_bidi as bidi
        result = bidi.query(ui.command_snapshot({}), str(payload.get("expression") or ""),
                            cursor=payload.get("cursor"), snapshot_reader=lambda: ui.command_snapshot({}))
    else:
        result = ui.COMMANDS[command](payload)
        if command == "status" and os.environ.get("FIREFOX_CONTROL_PROTOCOL") == "firefox-bidi-ui-v2":
            import secure_browser_bidi as bidi
            result["bidi_available"] = bidi.probe()
    result["bridge_diagnostics"] = {
        "command": command,
        "source_sha256": hashlib.sha256((ROOT / "firefox-ui-bridge.py").read_bytes()).hexdigest(),
        "endpoint_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "transport": "authenticated service endpoint",
    }
    return result


def controller_lease(path):
    # One resident journal owner. A hot server overlap must not dispatch from
    # two stale in-memory registries, even when individual requests serialize.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = path.open("a+")
    os.fchmod(handle.fileno(), 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("resident window controller already owns this journal") from None
    return handle


class Handler(BaseHTTPRequestHandler):
    server_version = "NestFirefoxBridge/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Never log URLs, payloads, headers or browser responses.

    def reply(self, code, value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.raw_reply(code, raw, "application/json")

    def raw_reply(self, code, raw, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; connect-src 'self'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Delivery may have completed: never retry it.

    def do_GET(self):
        if getattr(self.server, "windows", None) is None:
            return self.reply(404, {"status": "error"})
        assets = {"/_nest/bridge/window/": ("window-viewer.html", "text/html; charset=utf-8"),
                  "/_nest/bridge/window/viewer.js": ("window-viewer.js", "text/javascript; charset=utf-8")}
        if self.path not in assets:
            return self.reply(404, {"status": "error"})
        leaf, content_type = assets[self.path]
        self.raw_reply(200, (ROOT / leaf).read_bytes(), content_type)

    def owner_control(self):
        # Browser UI uses only a window capability, never the service token.
        # Require exact same-origin JSON, no CORS, redirects or URL secrets.
        windows = getattr(self.server, "windows", None)
        if (windows is None or self.headers.get("Origin") != "https://browser.eyrie"
                or self.headers.get("Upgrade") or self.headers.get("Transfer-Encoding")
                or self.headers.get_content_type() != "application/json"
                or len(self.headers.get_all("Content-Length", [])) != 1):
            return self.reply(403, {"status": "error"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2048:
                raise ValueError("bounded owner input required")
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Window ") or len(auth) > 200:
                raise ValueError("window capability required")
            capability = auth[7:]
            body = json.loads(self.rfile.read(size))
            with windows.operation():
                scope = windows.viewer_scope(capability)
                if body == {"command": "screenshot"}:
                    result = windows.dispatch("screenshot", {"scope": scope})
                    # No native IDs, cookies or page field values in owner UI.
                    result = {"status": "ok", "png_base64": result["png_base64"]}
                elif isinstance(body, dict) and set(body) == {"command", "payload"} and body["command"] == "input":
                    result = windows.owner_input(capability, body["payload"])
                else:
                    raise ValueError("unsupported owner operation")
        except Exception:
            return self.reply(409, {"status": "error", "message": "window operation unavailable or uncertain; input was not retried"})
        self.reply(200, result)

    def do_POST(self):
        started = time.monotonic()
        if self.path == "/_nest/bridge/window/control":
            return self.owner_control()
        if self.path != API_PATH:
            return self.reply(404, {"status": "error", "message": "unknown bridge route"})
        if self.headers.get("Origin") or self.headers.get("Upgrade") or self.headers.get("Transfer-Encoding"):
            return self.reply(403, {"status": "error", "message": "browser-origin and upgraded requests are forbidden"})
        expected = "Bearer " + self.server.bridge_token
        if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return self.reply(401, {"status": "error", "message": "endpoint authentication required"})
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("expected JSON")
            if len(self.headers.get_all("Content-Length", [])) != 1:
                raise ValueError("expected one content length")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_REQUEST:
                raise ValueError("request size exceeds the input budget")
            envelope = json.loads(self.rfile.read(size))
            command, payload = validate(envelope)
        except (ValueError, OSError):
            return self.reply(400, {"status": "error", "message": "invalid bounded command envelope"})
        LOCK_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with LOCK_PATH.open("a+") as lock:
            os.fchmod(lock.fileno(), 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self.reply(409, {"status": "error", "error": "FIREFOX_BUSY", "outcome": "not_started", "message": "shared Firefox endpoint busy; no operation started"})
            # Child retains this lock even if the HTTP server is refreshed.
            # Only the bridge worker is bounded; Firefox is never terminated.
            budget = min(len(str(payload.get("text") or payload.get("url") or "")), 4096) // 5
            try:
                windows = getattr(self.server, "windows", None)
                if windows is not None:
                    with windows.operation():
                        result = windows.lifecycle(payload) if command == "window_lifecycle" else windows.dispatch(command, payload)
                else:
                    proc = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()), "--worker"],
                        input=json.dumps(envelope), text=True, capture_output=True,
                        timeout=50 + budget, pass_fds=(lock.fileno(),), check=False,
                    )
                    if len(proc.stdout.encode()) > MAX_RESPONSE or proc.returncode:
                        raise RuntimeError("bridge worker failed")
                    result = json.loads(proc.stdout)
                if not isinstance(result, dict):
                    raise ValueError("invalid worker response")
                if len(json.dumps(result).encode()) > MAX_RESPONSE:
                    raise ValueError("bounded window response exceeded")
            except Exception as exc:
                if getattr(exc, "code", None) in {"FIREFOX_BUSY", "FIREFOX_IDENTITY_LOST", "FIREFOX_NATIVE_OUTCOME_UNCERTAIN", "FIREFOX_CREATION_UNCERTAIN", "FIREFOX_CREATE_REJECTED", "FIREFOX_BINDING_RETIRED", "FIREFOX_TARGET_UNAVAILABLE", "FIREFOX_OBSERVATION_UNAVAILABLE", "FIREFOX_WINDOW_BUDGET"}:
                    result = {"status": "error", "error": getattr(exc, "code"), "outcome": getattr(exc, "outcome"), "message": str(exc)}
                else:
                    result = {"status": "error", "error": "FIREFOX_OUTCOME_UNCERTAIN", "outcome": "uncertain", "message": "bounded Firefox operation failed or timed out; read back; retain the action key; do not replay"}
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        self.reply(200, result)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--reconcile-generation", default=os.environ.get("FIREFOX_GENERATION_RECONCILIATION_GRANT"),
                        help="local operator JSON grant; requires exact owner approval and journal hash")
    parser.add_argument("--recover-binding", help="local operator JSON grant; requires independently verified scoped approval")
    parser.add_argument("--recover-creation", help="local administrator JSON grant; requires authority for one scoped new binding")
    args = parser.parse_args()
    if args.worker:
        try:
            result = worker()
        except Exception as exc:
            # Existing command validation emits privacy-safe errors. Driver
            # exceptions are already scrubbed at their source.
            result = {"status": "error", "message": str(exc)[:1000]}
        print(json.dumps(result))
        return
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if len(token) < 32 or any(char.isspace() for char in token):
        raise SystemExit("Missing or invalid endpoint credential")
    server = Server(("0.0.0.0", 8766), Handler)
    server.bridge_token = token
    if os.environ.get("FIREFOX_CONTROL_PROTOCOL") == "firefox-windows-v3":
        from firefox_windows import Windows
        state_dir = Path(os.environ.get("FIREFOX_UI_STATE_DIR", "/home/kasm-user/.local/state/nest-firefox-ui"))
        server.controller_lease = controller_lease(state_dir / "windows-controller.lock")
        server.windows = Windows(state_dir / "windows.json")
        if args.reconcile_generation:
            server.windows.reconcile_generation(json.loads(args.reconcile_generation))
        if args.recover_binding:
            server.windows.authorize_binding(json.loads(args.recover_binding))
        if args.recover_creation:
            server.windows.authorize_creation_recovery(json.loads(args.recover_creation))
    server.serve_forever()


if __name__ == "__main__":
    main()
