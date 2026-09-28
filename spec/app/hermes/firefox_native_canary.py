#!/usr/bin/env python3
"""Non-purchasing, local Firefox/Marionette native-element integration canary.

Run inside a disposable Firefox+geckodriver container, never in browser.eyrie.
"""
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import socket
import subprocess
import tempfile
import threading
import time

BRIDGE = Path(__file__).resolve().parents[3] / "files/firefox-browser/firefox-ui-bridge.py"
spec = importlib.util.spec_from_file_location("firefox_ui_canary", BRIDGE)
assert spec is not None and spec.loader is not None
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

html = """<!doctype html><title>Local native element canary</title>
<button id='original' onclick='window.last={id:this.id,trusted:event.isTrusted}'>First</button>
<button id='replacement' onclick='window.last={id:this.id,trusted:event.isTrusted}'>Second</button>
<input id='public' aria-label='Note'><input id='secret' type='password'>
"""
class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        content = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/canary"
os.environ["FIREFOX_CONTROL_PROTOCOL"] = "firefox-bidi-ui-v2"
with tempfile.TemporaryDirectory() as profile:
    firefox = subprocess.Popen(["firefox", "--headless", "--no-remote", "--new-instance", "--marionette",
                                "--profile", profile, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            if firefox.poll() is not None:
                raise AssertionError("disposable Firefox exited")
            try:
                with socket.create_connection(("127.0.0.1", 2828), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("Marionette did not start")
        with bridge._webdriver() as command:
            assert len(command("GET", "/window/handles")) == 1
            command("POST", "/url", {"url": url})
            observed_url = command("GET", "/url")
            assert observed_url == url
            original = bridge._native_selector(command, {"url": bridge._redact_url(url)}, "#original", False)
            # Replacement at the original location after lookup must not receive
            # a click against a stale/covered original element handle.
            command("POST", "/execute/sync", {"script": """
                const a=document.querySelector('#original'), b=document.querySelector('#replacement');
                a.getBoundingClientRect(); b.style.position='absolute';
                const r=a.getBoundingClientRect(); b.style.left=r.left+'px'; b.style.top=r.top+'px';
                b.style.zIndex='999'; b.style.background='red';
                """, "args": []})
            try:
                command("POST", f"/element/{original}/click", {})
            except RuntimeError:
                pass
            else:
                raise AssertionError("native element click crossed an occluding replacement")
            assert command("POST", "/execute/sync", {"script": "return window.last || null", "args": []}) is None
            command("POST", "/execute/sync", {"script": "document.querySelector('#replacement').remove()", "args": []})
            command("POST", f"/element/{original}/click", {})
            assert command("POST", "/execute/sync", {"script": "return window.last", "args": []}) == {"id": "original", "trusted": True}
            public = bridge._native_selector(command, {"url": bridge._redact_url(url)}, "#public", True)
            command("POST", f"/element/{public}/value", {"text": "local canary"})
            assert command("POST", "/execute/sync", {"script": "return document.querySelector('#public').value", "args": []}) == "local canary"
            try:
                bridge._native_selector(command, {"url": bridge._redact_url(url)}, "#secret", True)
            except RuntimeError:
                pass
            else:
                raise AssertionError("secret field passed native guard")
        assert firefox.poll() is None, "WebDriver detach terminated the persistent Firefox process"
        with bridge._webdriver() as command:
            assert len(command("GET", "/window/handles")) == 1
            assert command("GET", "/url") == url
        print("local native Firefox canary passed: occlusion refused; trusted click, typing, secret guard, existing browser survived detach")
    finally:
        firefox.terminate()
        try:
            firefox.wait(timeout=10)
        except subprocess.TimeoutExpired:
            firefox.kill()
            firefox.wait()
        server.shutdown()
