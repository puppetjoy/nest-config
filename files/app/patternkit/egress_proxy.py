#!/usr/bin/env python3
"""Fail-closed HTTP CONNECT proxy for the isolated Pattern Kit workbench."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import select
import socket
from urllib.parse import urlsplit


HOST = os.environ.get("PATTERNKIT_EGRESS_PROXY_HOST", "0.0.0.0")
PORT = int(os.environ.get("PATTERNKIT_EGRESS_PROXY_PORT", "3128"))
ALLOWED_HOSTS = frozenset(
    host.strip().lower()
    for host in os.environ.get(
        "PATTERNKIT_EGRESS_ALLOWED_HOSTS",
        "patternkit.eyrie,gitlab.joyfullee.me",
    ).split(",")
    if host.strip()
)
MAX_REQUEST_BODY = 16 * 1024 * 1024


def _parse_authority(authority: str, default_port: int) -> tuple[str, int] | None:
    parsed = urlsplit(f"//{authority}")
    try:
        port = parsed.port or default_port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS or port not in {80, 443}:
        return None
    return host, port


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        print(f"patternkit-egress {self.client_address[0]} {self.command} {args[1] if len(args) > 1 else '-'}")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _connect(self, target: tuple[str, int]) -> socket.socket | None:
        try:
            return socket.create_connection(target, timeout=15)
        except OSError:
            self._send(HTTPStatus.BAD_GATEWAY, b"Allowed upstream unavailable\n")
            return None

    def _tunnel(self, upstream: socket.socket) -> None:
        try:
            sockets = [self.connection, upstream]
            while sockets:
                readable, _, _ = select.select(sockets, [], [])
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        sockets = []
                        break
                    (upstream if source is self.connection else self.connection).sendall(data)
        except (OSError, select.error):
            pass
        finally:
            upstream.close()
            self.close_connection = True

    def do_CONNECT(self) -> None:
        target = _parse_authority(self.path, 443)
        if target is None:
            self._send(HTTPStatus.FORBIDDEN, b"Destination is outside the Pattern Kit workbench allowlist\n")
            return
        upstream = self._connect(target)
        if upstream is None:
            return
        self.send_response(HTTPStatus.OK, "Connection Established")
        self.end_headers()
        self._tunnel(upstream)

    def _forward(self) -> None:
        parsed = urlsplit(self.path)
        target = _parse_authority(parsed.netloc, 80)
        if parsed.scheme != "http" or target is None:
            self._send(HTTPStatus.FORBIDDEN, b"Destination is outside the Pattern Kit workbench allowlist\n")
            return
        try:
            body_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, b"Invalid Content-Length\n")
            return
        if body_length < 0 or body_length > MAX_REQUEST_BODY or self.headers.get("Transfer-Encoding"):
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"Unsupported request body\n")
            return
        upstream = self._connect(target)
        if upstream is None:
            return
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        headers = []
        for name, value in self.headers.items():
            if name.lower() not in {"connection", "host", "proxy-authorization", "proxy-connection"}:
                headers.append((name, value))
        headers.extend((("Host", parsed.netloc), ("Connection", "close")))
        body = self.rfile.read(body_length) if body_length else b""
        try:
            head = f"{self.command} {path} HTTP/1.1\r\n" + "".join(f"{name}: {value}\r\n" for name, value in headers) + "\r\n"
            upstream.sendall(head.encode("latin1") + body)
            while True:
                data = upstream.recv(65536)
                if not data:
                    break
                self.connection.sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()
            self.close_connection = True

    do_GET = _forward
    do_HEAD = _forward
    do_POST = _forward
    do_PUT = _forward
    do_PATCH = _forward
    do_DELETE = _forward


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()