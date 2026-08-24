#!/usr/bin/env python3
"""Small GitLab OAuth/PKCE reverse proxy for private Eyrie development apps."""

from __future__ import annotations

import base64
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import select
import secrets
import socket
import ssl
import subprocess
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

LISTEN_HOST = os.environ.get("OAUTH_PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("OAUTH_PROXY_PORT", "4180"))
UPSTREAM_HOST = os.environ.get("OAUTH_PROXY_UPSTREAM_HOST", "127.0.0.1")
UPSTREAM_PORT = int(os.environ["OAUTH_PROXY_UPSTREAM_PORT"])
UPSTREAM_TLS = os.environ.get("OAUTH_PROXY_UPSTREAM_TLS", "false").lower() == "true"
PUBLIC_ORIGIN = os.environ["OAUTH_PROXY_PUBLIC_ORIGIN"].rstrip("/")
CLIENT_ID = os.environ["OAUTH_PROXY_CLIENT_ID"]
GITLAB_ORIGIN = os.environ.get("OAUTH_PROXY_GITLAB_ORIGIN", "https://gitlab.joyfullee.me").rstrip("/")
SMOKE_TOKEN = os.environ.get("OAUTH_PROXY_SMOKE_TOKEN", "")
BRIDGE_TOKEN = os.environ.get("OAUTH_PROXY_BRIDGE_TOKEN", "")
SOURCE_REPOS = [item for item in os.environ.get("OAUTH_PROXY_SOURCE_REPOS", "").split(":") if item]
NODE_NAME = os.environ.get("PATTERNKIT_NODE_NAME", "")
COOKIE_NAME = "__Host-patternkit_session"
STATE_COOKIE_NAME = "__Host-patternkit_oauth_state"
SESSION_TTL = 12 * 60 * 60
PENDING_TTL = 10 * 60
MAX_PENDING_STATES = 1024
MAX_REQUEST_BODY = 16 * 1024 * 1024

_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_sessions: dict[str, dict[str, Any]] = {}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _prune() -> None:
    now = time.time()
    with _lock:
        for mapping in (_pending, _sessions):
            expired = [key for key, value in mapping.items() if float(value["expires_at"]) <= now]
            for key in expired:
                mapping.pop(key, None)


def _cookie(headers) -> str | None:
    raw = headers.get("Cookie", "")
    for item in raw.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == COOKIE_NAME:
            return value
    return None


def _upstream_cookie(raw: str) -> str:
    values = []
    for item in raw.split(";"):
        name, separator, _value = item.strip().partition("=")
        if separator and name not in {COOKIE_NAME, STATE_COOKIE_NAME}:
            values.append(item.strip())
    return "; ".join(values)


def _json_request(url: str, *, data: dict[str, str] | None = None) -> dict[str, object]:
    encoded = urlencode(data).encode() if data is not None else None
    request = Request(url, data=encoded, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read())


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # Do not log query strings, OAuth codes, cookies, or user content.
        print(f'oauth-proxy {self.client_address[0]} {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else "-"}')

    def _send(self, status: int, body: bytes = b"", *, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, location: str, *, cookies: tuple[str, ...] = ()) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login(self) -> None:
        _prune()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        requested = self.headers.get("X-Forwarded-Uri") or self.path
        if not requested.startswith("/") or requested.startswith("//"):
            requested = "/"
        with _lock:
            if len(_pending) >= MAX_PENDING_STATES:
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"Too many pending OAuth requests\n")
                return
            _pending[state] = {
                "verifier": verifier,
                "requested": requested,
                "expires_at": time.time() + PENDING_TTL,
            }
        query = urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": f"{PUBLIC_ORIGIN}/_oauth/callback",
            "response_type": "code",
            "scope": "read_user",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        state_cookie = f"{STATE_COOKIE_NAME}={state}; Path=/; Max-Age={PENDING_TTL}; Secure; HttpOnly; SameSite=Lax"
        self._redirect(f"{GITLAB_ORIGIN}/oauth/authorize?{query}", cookies=(state_cookie,))

    def _callback(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        cookie_state = None
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == STATE_COOKIE_NAME:
                cookie_state = value
                break
        with _lock:
            pending = _pending.pop(state, None)
        if not pending or not code or not cookie_state or not secrets.compare_digest(cookie_state, state) or float(pending["expires_at"]) <= time.time():
            self._send(HTTPStatus.BAD_REQUEST, b"Invalid or expired OAuth callback\n")
            return
        try:
            token = _json_request(
                f"{GITLAB_ORIGIN}/oauth/token",
                data={
                    "client_id": CLIENT_ID,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": f"{PUBLIC_ORIGIN}/_oauth/callback",
                    "code_verifier": str(pending["verifier"]),
                },
            )
            access_token = str(token["access_token"])
            request = Request(
                f"{GITLAB_ORIGIN}/api/v4/user",
                headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            )
            with urlopen(request, timeout=15) as response:
                user = json.loads(response.read())
            username = str(user.get("username", "")).strip()
            if not username:
                raise ValueError("GitLab user response lacked a username")
        except (HTTPError, OSError, KeyError, ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_GATEWAY, b"GitLab authentication failed\n")
            return
        session = secrets.token_urlsafe(48)
        with _lock:
            _sessions[session] = {"username": username, "expires_at": time.time() + SESSION_TTL}
        cookie = f"{COOKIE_NAME}={session}; Path=/; Max-Age={SESSION_TTL}; Secure; HttpOnly; SameSite=Lax"
        clear_state = f"{STATE_COOKIE_NAME}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"
        self._redirect(str(pending["requested"]), cookies=(cookie, clear_state))

    def _identity(self) -> str | None:
        _prune()
        if BRIDGE_TOKEN and secrets.compare_digest(self.headers.get("X-PatternKit-Bridge-Token", ""), BRIDGE_TOKEN):
            return "star"
        if SMOKE_TOKEN and secrets.compare_digest(self.headers.get("X-PatternKit-Smoke-Token", ""), SMOKE_TOKEN):
            return "synthetic-smoke"
        session = _cookie(self.headers)
        with _lock:
            details = _sessions.get(session or "")
            if details and float(details["expires_at"]) > time.time():
                return str(details["username"])
        return None

    def _source_status(self) -> dict[str, object]:
        repositories = []
        for path in SOURCE_REPOS:
            try:
                revision = subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True, timeout=3).strip()
                branch = subprocess.check_output(["git", "-C", path, "branch", "--show-current"], text=True, timeout=3).strip()
                dirty = bool(subprocess.check_output(["git", "-C", path, "status", "--short"], text=True, timeout=3).strip())
                repositories.append({"path": path, "revision": revision, "branch": branch, "dirty": dirty})
            except (OSError, subprocess.SubprocessError):
                repositories.append({"path": path, "error": "status-unavailable"})
        return {
            "schema": "patternkit.deployment-status/v1",
            "origin": PUBLIC_ORIGIN,
            "node": NODE_NAME,
            "repositories": repositories,
        }

    def _wrapper(self) -> None:
        body = b"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Pattern Kit Studio</title>
<style>html,body{height:100%;margin:0;background:#17151d;color:#eee8f5;font:13px system-ui}header{height:32px;display:flex;align-items:center;gap:1rem;padding:0 .8rem;background:#24202c;border-bottom:1px solid #554768}header a{color:#cfb8ff}iframe{border:0;width:100%;height:calc(100% - 33px)}</style></head>
<body><header><strong>Pattern Kit Studio</strong><span id="revision">loading source status...</span><a href="/__patternkit/status" target="_blank">details</a></header><iframe title="Pattern Kit Studio" src="/studio/"></iframe>
<script>fetch('/__patternkit/status').then(r=>r.json()).then(s=>{document.getElementById('revision').textContent=s.repositories.map(r=>`${r.path.split('/').pop()}: ${r.branch||'?'}@${(r.revision||'?').slice(0,10)}${r.dirty?' dirty':''}`).join(' | ')})</script></body></html>"""
        self._send(HTTPStatus.OK, body, headers={"Content-Type": "text/html; charset=utf-8"})

    def _proxy(self, identity: str) -> None:
        if self.headers.get("Transfer-Encoding"):
            self._send(HTTPStatus.NOT_IMPLEMENTED, b"Streaming request bodies are not supported\n")
            return
        upstream_socket: socket.socket | None = None
        try:
            upstream_socket = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=15)
            if UPSTREAM_TLS:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                upstream = context.wrap_socket(upstream_socket, server_hostname=UPSTREAM_HOST)
            else:
                upstream = upstream_socket
        except (OSError, ssl.SSLError):
            if upstream_socket is not None:
                upstream_socket.close()
            self._send(HTTPStatus.BAD_GATEWAY, b"Upstream application unavailable\n")
            return
        path = self.path
        if path == "/studio" or path.startswith("/studio?"):
            path = "/" + path[len("/studio"):].lstrip("/")
        elif path.startswith("/studio/"):
            path = "/" + path[len("/studio/"):]
        try:
            body_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, b"Invalid Content-Length\n")
            upstream.close()
            return
        if body_length < 0 or body_length > MAX_REQUEST_BODY:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"Request body too large\n")
            upstream.close()
            return
        body = self.rfile.read(body_length) if body_length else b""
        headers: list[tuple[str, str]] = []
        for name, value in self.headers.items():
            lowered = name.lower()
            if lowered == "cookie":
                upstream_cookie = _upstream_cookie(value)
                if upstream_cookie:
                    headers.append((name, upstream_cookie))
                continue
            if (
                lowered in {
                    "connection",
                    "host",
                    "keep-alive",
                    "proxy-authenticate",
                    "proxy-authorization",
                    "proxy-connection",
                    "te",
                    "trailer",
                    "x-patternkit-bridge-token",
                    "x-patternkit-smoke-token",
                }
                or lowered.startswith("x-forwarded-")
            ):
                continue
            headers.append((name, value))
        websocket = self.headers.get("Upgrade", "").lower() == "websocket"
        headers.extend([
            ("Host", f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"),
            ("X-Forwarded-User", identity),
            ("X-Forwarded-Host", urlsplit(PUBLIC_ORIGIN).netloc),
            ("X-Forwarded-Proto", "https"),
            ("Connection", "Upgrade" if websocket else "close"),
        ])
        request_head = f"{self.command} {path} HTTP/1.1\r\n" + "".join(f"{name}: {value}\r\n" for name, value in headers) + "\r\n"
        response_started = False
        try:
            upstream.sendall(request_head.encode("latin1") + body)
            if websocket:
                response_head = b""
                while b"\r\n\r\n" not in response_head and len(response_head) <= 65536:
                    chunk = upstream.recv(65536)
                    if not chunk:
                        break
                    response_head += chunk
                if b"\r\n\r\n" not in response_head or len(response_head) > 65536:
                    raise OSError("invalid WebSocket upstream response")
                status_line = response_head.split(b"\r\n", 1)[0]
                if not status_line.startswith(b"HTTP/1.1 101 "):
                    self.connection.sendall(response_head)
                    response_started = True
                    self.close_connection = True
                    return
                self.connection.sendall(response_head)
                response_started = True
                sockets = [self.connection, upstream]
                while sockets:
                    readable, _, _ = select.select(sockets, [], [])
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            sockets = []
                            break
                        destination = upstream if source is self.connection else self.connection
                        destination.sendall(data)
            else:
                while True:
                    data = upstream.recv(65536)
                    if not data:
                        break
                    response_started = True
                    self.connection.sendall(data)
                if not response_started:
                    raise OSError("upstream closed without a response")
        except (OSError, select.error):
            if not response_started:
                self._send(HTTPStatus.BAD_GATEWAY, b"Upstream application unavailable\n")
        finally:
            upstream.close()
        self.close_connection = True

    def _dispatch(self) -> None:
        path = urlsplit(self.path).path
        if path == "/_oauth/health":
            self._send(HTTPStatus.OK, b"ok\n", headers={"Content-Type": "text/plain"})
            return
        if path == "/_oauth/callback":
            self._callback()
            return
        if path == "/_oauth/logout":
            session = _cookie(self.headers)
            with _lock:
                _sessions.pop(session or "", None)
            self._redirect("/", cookies=(f"{COOKIE_NAME}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax",))
            return
        identity = self._identity()
        if identity is None:
            self._login()
            return
        if path == "/__patternkit/status":
            body = (json.dumps(self._source_status(), sort_keys=True) + "\n").encode()
            self._send(HTTPStatus.OK, body, headers={"Content-Type": "application/json"})
            return
        if path == "/" and UPSTREAM_PORT != 6901:
            self._wrapper()
            return
        self._proxy(identity)

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler).serve_forever()
