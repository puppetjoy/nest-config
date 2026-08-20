#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import socket
import socketserver
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.dont_write_bytecode = True
os.environ.setdefault("OAUTH_PROXY_UPSTREAM_PORT", "8765")
os.environ.setdefault("OAUTH_PROXY_PUBLIC_ORIGIN", "https://patternkit.eyrie")
os.environ.setdefault("OAUTH_PROXY_CLIENT_ID", "test-client")

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_PATH = REPO_ROOT / "files/app/patternkit/oauth_proxy.py"
SPEC = importlib.util.spec_from_file_location("patternkit_oauth_proxy", PROXY_PATH)
assert SPEC and SPEC.loader
PROXY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROXY)


class UpstreamCookieTest(unittest.TestCase):
    def test_strips_only_proxy_owned_cookies(self) -> None:
        raw = (
            "kasm_session=keep-me; "
            f"{PROXY.COOKIE_NAME}=proxy-secret; "
            "application_preference=also-keep; "
            f"{PROXY.STATE_COOKIE_NAME}=oauth-secret"
        )
        self.assertEqual(
            PROXY._upstream_cookie(raw),
            "kasm_session=keep-me; application_preference=also-keep",
        )

    def test_proxy_source_strips_all_caller_forwarded_headers(self) -> None:
        source = PROXY_PATH.read_text()
        self.assertIn('lowered.startswith("x-forwarded-")', source)
        self.assertIn('(\"X-Forwarded-User\", identity)', source)
        self.assertIn('(\"X-Forwarded-Host\", urlsplit(PUBLIC_ORIGIN).netloc)', source)
        self.assertIn('(\"X-Forwarded-Proto\", \"https\")', source)

    def test_proxy_caps_request_bodies(self) -> None:
        self.assertEqual(PROXY.MAX_REQUEST_BODY, 16 * 1024 * 1024)
        self.assertGreater(PROXY.MAX_PENDING_STATES, 0)


class ProxyBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = (PROXY.UPSTREAM_HOST, PROXY.UPSTREAM_PORT, PROXY.UPSTREAM_TLS, PROXY.SMOKE_TOKEN)
        PROXY.__dict__.update({
            "UPSTREAM_HOST": "127.0.0.1",
            "UPSTREAM_TLS": False,
            "SMOKE_TOKEN": "test-smoke-token",
        })

    def tearDown(self) -> None:
        host, port, tls, token = self.previous
        PROXY.__dict__.update({"UPSTREAM_HOST": host, "UPSTREAM_PORT": port, "UPSTREAM_TLS": tls, "SMOKE_TOKEN": token})

    @staticmethod
    def proxy_server():
        server = PROXY.ThreadingHTTPServer(("127.0.0.1", 0), PROXY.ProxyHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_unavailable_upstream_returns_bad_gateway(self) -> None:
        unavailable = socket.socket()
        unavailable.bind(("127.0.0.1", 0))
        PROXY.__dict__["UPSTREAM_PORT"] = unavailable.getsockname()[1]
        unavailable.close()
        server, thread = self.proxy_server()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/health",
                headers={"X-PatternKit-Smoke-Token": "test-smoke-token"},
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 502)
            self.assertEqual(raised.exception.read(), b"Upstream application unavailable\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_websocket_upgrade_relays_data_in_both_directions(self) -> None:
        class WebSocketEcho(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                request = b""
                while b"\r\n\r\n" not in request:
                    request += self.request.recv(65536)
                self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                self.request.sendall(b"echo:" + self.request.recv(4))

        upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), WebSocketEcho)
        upstream.daemon_threads = True
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        PROXY.__dict__["UPSTREAM_PORT"] = upstream.server_address[1]
        server, thread = self.proxy_server()
        client = socket.create_connection(("127.0.0.1", server.server_port), timeout=5)
        try:
            client.sendall(
                b"GET /socket HTTP/1.1\r\n"
                b"Host: patternkit.eyrie\r\n"
                b"Connection: Upgrade\r\n"
                b"Upgrade: websocket\r\n"
                b"X-PatternKit-Smoke-Token: test-smoke-token\r\n\r\n"
            )
            response = b""
            while b"\r\n\r\n" not in response:
                response += client.recv(65536)
            self.assertTrue(response.startswith(b"HTTP/1.1 101 Switching Protocols\r\n"), response)
            client.sendall(b"ping")
            self.assertEqual(client.recv(9), b"echo:ping")
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(5)
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(5)


if __name__ == "__main__":
    unittest.main()