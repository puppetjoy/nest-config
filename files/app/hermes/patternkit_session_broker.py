#!/usr/bin/env python3
"""Root-owned fixed-function broker for Star's Pattern Kit session plugin."""

from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import queue
import re
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

SOCKET_PATH = Path(os.environ.get("PATTERNKIT_SESSION_SOCKET", "/run/patternkit-session-broker/patternkit-session.sock"))
SOCKET_GROUP = os.environ.get("PATTERNKIT_SESSION_SOCKET_GROUP", "joy")
NAMESPACE = os.environ.get("PATTERNKIT_SESSION_NAMESPACE", "ai")
SERVICE = os.environ.get("PATTERNKIT_SESSION_SERVICE", "patternkit-workbench")
REMOTE_PORT = int(os.environ.get("PATTERNKIT_SESSION_BRIDGE_PORT", "8766"))
LOCAL_PORT = int(os.environ.get("PATTERNKIT_SESSION_LOCAL_PORT", "0"))
KUBECTL = os.environ.get("PATTERNKIT_SESSION_KUBECTL", "/usr/bin/kubectl")
KUBECONFIG = os.environ.get("PATTERNKIT_SESSION_KUBECONFIG", "/home/joy/.kube/config")
TOKEN = os.environ.get("PATTERNKIT_SESSION_BRIDGE_TOKEN", "").strip()
PROC_ROOT = Path(os.environ.get("PATTERNKIT_SESSION_PROC_ROOT", "/proc"))
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_ACTIVE_LOCAL_PORT = 0
_ALLOWED_GET = {
    "/agent/status",
    "/agent/runtime-canary",
    "/agent/snapshot",
    "/agent/visual",
    "/agent/diagnostics",
}
_ALLOWED_POST = {"/agent/control", "/agent/input"}


class BrokerError(RuntimeError):
    pass


def _safe_path(method: str, target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/agent/"):
        raise BrokerError("unsupported broker route")
    allowed = _ALLOWED_GET if method == "GET" else _ALLOWED_POST if method == "POST" else set()
    if parsed.path not in allowed:
        raise BrokerError("unsupported broker route")
    query = parse_qs(parsed.query, keep_blank_values=True)
    allowed_queries = {
        "/agent/runtime-canary": set(),
        "/agent/status": {"session"},
        "/agent/snapshot": {"session"},
        "/agent/visual": {"session"},
        "/agent/diagnostics": {"session", "observe_seconds", "slow_ms"},
        "/agent/control": set(),
        "/agent/input": set(),
    }
    if not set(query) <= allowed_queries[parsed.path] or any(len(values) != 1 for values in query.values()):
        raise BrokerError("unsupported broker query")
    return target


def _peer_is_star_gateway(connection: socket.socket) -> bool:
    """Bind broker access to the systemd cgroup of Star's gateway process."""
    try:
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, _uid, _gid = struct.unpack("3i", credentials)
        cgroup = (PROC_ROOT / str(pid) / "cgroup").read_text()
    except (OSError, ValueError, struct.error):
        return False
    expected_unit = "hermes-gateway@star.service"
    for line in cgroup.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and expected_unit in Path(fields[2]).parts:
            return True
    return False


def _forward(method: str, target: str, body: bytes) -> tuple[int, bytes]:
    if not TOKEN:
        raise BrokerError("broker credential is unavailable")
    local_port = LOCAL_PORT or _ACTIVE_LOCAL_PORT
    if not local_port:
        raise BrokerError("broker port-forward is unavailable")
    connection = http.client.HTTPConnection("127.0.0.1", local_port, timeout=20)
    headers = {"X-PatternKit-Agent-Token": TOKEN, "Accept": "application/json"}
    if method == "POST":
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, _safe_path(method, target), body=body or None, headers=headers)
        response = connection.getresponse()
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise BrokerError("bridge response exceeded the broker limit")
        content_type = response.getheader("Content-Type", "")
        if "application/json" not in content_type.lower():
            raise BrokerError("bridge returned an unsupported response")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise BrokerError("bridge returned an unsupported response")
        return response.status, json.dumps(decoded, separators=(",", ":")).encode()
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        raise BrokerError("Pattern Kit bridge is unavailable") from exc
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "PatternKitSessionBroker/1"

    def log_message(self, format: str, *_args: object) -> None:
        del format
        return

    def _reply(self, status: int, payload: dict[str, object] | bytes) -> None:
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle(self, method: str) -> None:
        try:
            if not _peer_is_star_gateway(self.connection):
                raise BrokerError("broker caller is not Star's managed gateway")
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise BrokerError("request exceeded the broker limit")
            body = self.rfile.read(length) if length else b""
            if method == "POST":
                decoded = json.loads(body)
                if not isinstance(decoded, dict):
                    raise BrokerError("request must be a JSON object")
                body = json.dumps(decoded, separators=(",", ":")).encode()
            status, payload = _forward(method, self.path, body)
            self._reply(status, payload)
        except (BrokerError, json.JSONDecodeError, ValueError):
            self._reply(400, {"error": "Pattern Kit broker rejected the request"})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_HEAD(self) -> None:
        self._reply(405, {"error": "method not allowed"})


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path):
        super().__init__("localhost", timeout=20)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.socket_path))


def _read_port_forward_output(process: subprocess.Popen[str], lines: queue.Queue[str]) -> None:
    if process.stdout is not None:
        for line in process.stdout:
            try:
                lines.put_nowait(line.strip())
            except queue.Full:
                pass


def _wait_for_port(process: subprocess.Popen[str]) -> int:
    deadline = time.monotonic() + 20
    if process.stdout is None:
        raise BrokerError("kubectl port-forward output is unavailable")
    lines: queue.Queue[str] = queue.Queue(maxsize=32)
    threading.Thread(target=_read_port_forward_output, args=(process, lines), daemon=True).start()
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrokerError("kubectl port-forward exited before becoming ready")
        try:
            line = lines.get(timeout=min(0.25, max(0.0, deadline - time.monotonic())))
        except queue.Empty:
            continue
        match = re.fullmatch(r"Forwarding from 127\.0\.0\.1:(\d+) -> (\d+)", line)
        if match and int(match.group(2)) == REMOTE_PORT:
            port = int(match.group(1))
            if LOCAL_PORT and port != LOCAL_PORT:
                raise BrokerError("kubectl reported an unexpected local port")
            return port
    raise BrokerError("kubectl port-forward did not become ready")


def _port_forward() -> subprocess.Popen[str]:
    environment = {
        "HOME": "/root",
        "KUBECONFIG": KUBECONFIG,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    process = subprocess.Popen(
        [
            KUBECTL,
            "--kubeconfig",
            KUBECONFIG,
            "-n",
            NAMESPACE,
            "port-forward",
            "--address",
            "127.0.0.1",
            f"service/{SERVICE}",
            f"{LOCAL_PORT}:{REMOTE_PORT}" if LOCAL_PORT else f":{REMOTE_PORT}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    global _ACTIVE_LOCAL_PORT
    try:
        _ACTIVE_LOCAL_PORT = _wait_for_port(process)
    except BrokerError:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise
    return process


def _stop_server_when_port_forward_exits(process: subprocess.Popen[str], server: UnixServer) -> None:
    process.wait()
    server.shutdown()


def _probe() -> int:
    connection = UnixHTTPConnection(SOCKET_PATH)
    try:
        connection.request("GET", "/agent/runtime-canary")
        response = connection.getresponse()
        payload = json.loads(response.read(MAX_RESPONSE_BYTES + 1))
        if response.status != 200 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise BrokerError("runtime canary did not pass")
        print("patternkit-session-broker: ready")
        return 0
    except (OSError, http.client.HTTPException, json.JSONDecodeError, BrokerError) as exc:
        print(f"patternkit-session-broker: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()


def _serve() -> int:
    if not TOKEN:
        print("patternkit-session-broker: credential is unavailable", file=sys.stderr)
        return 1
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists() or SOCKET_PATH.is_socket():
        SOCKET_PATH.unlink()
    process = _port_forward()
    server = UnixServer(str(SOCKET_PATH), Handler)
    try:
        import grp

        os.chown(SOCKET_PATH, 0, grp.getgrnam(SOCKET_GROUP).gr_gid)
        os.chmod(SOCKET_PATH, 0o660)
        signal.signal(signal.SIGTERM, lambda *_args: threading.Thread(target=server.shutdown, daemon=True).start())
        signal.signal(signal.SIGINT, lambda *_args: threading.Thread(target=server.shutdown, daemon=True).start())
        threading.Thread(target=_stop_server_when_port_forward_exits, args=(process, server), daemon=True).start()
        server.serve_forever()
        return 1 if process.poll() is not None else 0
    finally:
        server.server_close()
        if SOCKET_PATH.exists() or SOCKET_PATH.is_socket():
            SOCKET_PATH.unlink()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    return _probe() if args.probe else _serve()


if __name__ == "__main__":
    raise SystemExit(main())
