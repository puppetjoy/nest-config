"""Run only in a disposable Firefox image, with no owner mounts or network.

Tests native concurrent windows under the image's unmodified xmonad Full layout.
Synthetic login continuity is observed server-side; no cookie export operation.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import importlib.util
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/opt/nest/firefox/bin")
from firefox_windows import Windows, driver_request
from PIL import Image

login_seen = []
long_text = "Synthetic nonsecret source line. " * 400


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        logged_in = "fixture-session=shared" in self.headers.get("Cookie", "")
        login_seen.append((self.path, logged_in))
        color = "#ee1111" if self.path.startswith("/alpha") else "#1122ee" if self.path.startswith("/beta") else "#11ee11"
        body = (f'<title>Fixture {self.path}</title><body style="background:{color}">'
                f'<h1>{"Signed in" if logged_in else "Guest"}</h1>'
                '<textarea id="draft" autofocus></textarea><input id="password" type="password">'
                '<script>window.sends=0;document.querySelector("#draft").addEventListener("keydown",e=>{'
                'if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();window.sends++}})</script>'
                '<button aria-label="Edit repository metadata" onclick="document.querySelector(\'h1\').textContent=\'Clicked\'">Click</button>'
                '<div style="display:none"><button aria-label="Edit repository metadata">Hidden responsive duplicate</button></div>'
                '<p>Subtotal $12.00</p><p>Tax $2.00</p><p>Total $14.00</p>'
                f'<pre id="long" style="width:300px;white-space:pre-wrap">{long_text}</pre></body>').encode()
        self.send_response(200)
        if self.path == "/login":
            self.send_header("Set-Cookie", "fixture-session=shared; Path=/; HttpOnly; SameSite=Strict")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def focus():
    return subprocess.check_output(["xdotool", "getwindowfocus"], text=True).strip()


def emit(stage, **values):
    print(json.dumps({"stage": stage, **values}), flush=True)


emit("source", sha256={leaf: hashlib.sha256(Path("/opt/nest/firefox/bin", leaf).read_bytes()).hexdigest()
    for leaf in ["firefox_windows.py", "firefox-bridge-server.py"]})
# Native startup readiness only; no browser operation is retried.
deadline = time.monotonic() + 40
while True:
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=1):
            break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(.2)
server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}"
engine = Windows("/tmp/nest-firefox/window-canary.json")
scopes = ["kanban:canary:t_alpha", "kanban:canary:t_beta"]
try:
    # Fresh image installs Bitwarden and opens its first-run tab. Every page
    # here belongs to this disposable fixture, never to the production owner.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        initial = engine._tree()
        if len(initial) > 1:
            break
        time.sleep(.2)
    for extra in initial[1:]:
        engine._call("browsingContext.close", {"context": extra["context"], "promptUnload": False})
    emit("disposable-first-run-setup", closed_fixture_tabs=len(initial) - 1)
    root = engine.acquire("owner")
    # Firefox's singleton protocol limit is deterministic, not a graphical
    # hang. The supported resident route must keep working after this refused
    # independent session.new. Never end the existing classic session.
    import websockets.sync.client
    with websockets.sync.client.connect("ws://127.0.0.1:9222/session", open_timeout=5, close_timeout=2, proxy=None) as competing:
        competing.send(json.dumps({"id": 1, "method": "session.new", "params": {"capabilities": {"alwaysMatch": {}}}}))
        refusal = json.loads(competing.recv(timeout=10))
        assert refusal.get("type") == "error" and "Maximum number of active sessions" in refusal.get("message", "")
    assert engine.acquire("owner")["context"] == root["context"]
    emit("singleton-session-reproduction", independent_session_refused=True, resident_session_retained=True)
    engine.dispatch("navigate", {"scope": "owner", "url": url + "/login"})
    root_extra = engine._call("browsingContext.create", {"type": "tab", "referenceContext": root["context"], "background": True})["context"]
    engine._call("browsingContext.navigate", {"context": root_extra, "url": url + "/owner-second", "wait": "complete"})
    assert engine.acquire("owner")["context"] == root["context"]
    # Root is the initial Full-layout focus. No activate call is made by the engine.
    before = focus()
    with ThreadPoolExecutor(max_workers=2) as pool:
        bindings = list(pool.map(engine.acquire, scopes))
    emit("creation", distinct_windows=bindings[0]["window"] != bindings[1]["window"], focus_unchanged=before == focus())
    assert before == focus(), "new windows stole the owner's X11 focus"
    for index, scope in enumerate(scopes):
        engine.dispatch("navigate", {"scope": scope, "url": url + ("/alpha" if index == 0 else "/beta")})
    assert all(logged for path, logged in login_seen if path in {"/alpha", "/beta"})
    emit("shared-login", confirmed=True, exported_cookie=False)
    # Responsive pages repeat labels in hidden layouts. Only one rendered
    # match is admissible; real visible duplicates must still fail closed.
    selector = 'button[aria-label="Edit repository metadata"]'
    clicked = engine.dispatch("selector_action", {"scope": scopes[0], "operation": "click", "selector": selector,
        "action_key": "responsive-about-click"})
    assert clicked["status"] == "delivered"
    assert engine._evaluate(bindings[0]["context"], "document.querySelector('h1').textContent") == "Clicked"
    engine._evaluate(bindings[0]["context"], "document.querySelector('div[style]').style.display='block'")
    try:
        engine.dispatch("selector_action", {"scope": scopes[0], "operation": "click", "selector": selector,
            "action_key": "ambiguous-about-click"})
        raise AssertionError("visible duplicate accepted")
    except RuntimeError as exc:
        assert getattr(exc, "code", None) == "FIREFOX_TARGET_UNAVAILABLE"
        assert getattr(exc, "outcome", None) == "not_started"
    assert "ambiguous-about-click" not in engine.state["actions"]
    emit("responsive-selector", hidden_duplicate_clicked=True, visible_duplicate_refused=True, no_rejected_input_journal=True)
    # Same-URL contexts still resolve by immutable native binding.
    for scope in scopes:
        engine.dispatch("navigate", {"scope": scope, "url": url + "/alpha"})
    for index, scope in enumerate(scopes):
        key = "alpha\nsecond line" if index == 0 else "beta"
        emit("fixture-target-geometry", scope=scope, observation=engine._evaluate(bindings[index]["context"],
            "(()=>{const e=document.querySelector('#draft'),r=e.getBoundingClientRect();return {width:innerWidth,height:innerHeight,visibility:document.visibilityState,rect:{x:r.x,y:r.y,w:r.width,h:r.height},hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.localName||null}})()"))
        result = engine.dispatch("selector_action", {"scope": scope, "operation": "type", "selector": "#draft", "mode": "replace", "text": key, "action_key": "canary-" + key})
        emit("typing", scope=scope, status=result["status"], confirmation=result["delivery"])
        assert result["status"] == "input_readback_confirmed"
        assert engine._evaluate(bindings[index]["context"], "window.sends") == 0
        again = engine.dispatch("selector_action", {"scope": scope, "operation": "type", "selector": "#draft", "mode": "replace", "text": key, "action_key": "canary-" + key})
        assert again["delivery"]["input_sent"] is False
    inserted = engine.dispatch("selector_action", {"scope": scopes[0], "operation": "type", "selector": "#draft",
        "text": "\nthird line", "action_key": "canary-multiline-insert"})
    assert inserted["status"] == "input_readback_confirmed"
    assert engine._evaluate(bindings[0]["context"], "window.sends") == 0
    emit("multiline-entry-replacement", confirmed=True, send_count=0)
    assert engine._evaluate(root["context"], 'document.querySelector("#draft").value') == ""
    values = [engine._evaluate(b["context"], 'document.querySelector("#draft").value') for b in bindings]
    assert values == ["alpha\nsecond line\nthird line", "beta"]
    emit("duplicate-url-input-isolation", confirmed=True, root_empty=True, focus_unchanged=before == focus())
    # Distinct pixel fixtures prove context screenshots are not global capture.
    for index, scope in enumerate(scopes):
        engine.dispatch("navigate", {"scope": scope, "url": url + ("/alpha" if index == 0 else "/beta")})
    for scope, expected in zip(scopes, [(238, 17, 17), (17, 34, 238)]):
        shot = engine.dispatch("screenshot", {"scope": scope})
        image = Image.open(io.BytesIO(base64.b64decode(shot["png_base64"]))).convert("RGB")
        pixel = image.getpixel((image.width - 20, image.height - 20))
        emit("viewport-pixels", scope=scope, expected=list(expected), actual=list(pixel), matched=pixel == expected)
        assert pixel == expected
    for scope in scopes:
        for _ in range(5):
            engine.dispatch("tabs", {"scope": scope, "action": "release"})
            engine.acquire(scope)
    assert len(engine._tree()) == 4
    for _ in range(3):
        # Disconnect only the observer, then reconstruct the controller from
        # its journal as after a bridge process crash. Never create a session.
        engine.browser.close()
        engine = Windows("/tmp/nest-firefox/window-canary.json")
        for index, scope in enumerate(scopes):
            assert engine.acquire(scope)["context"] == bindings[index]["context"]
        assert len(engine._tree()) == 4
    emit("observer-reconnect", repeated=3, window_count=3, context_count=4, native_ids_preserved=True)
    cursor = None
    collected = ""
    while True:
        result = engine.dispatch("query", {"scope": scopes[0], "expression": 'document.readText("#long",0)', "cursor": cursor})
        collected += result["value"]["text"]
        cursor = result["nextCursor"]
        if result["complete"]:
            break
    assert collected == long_text
    assert engine.dispatch("wait", {"scope": scopes[0], "max_wait_seconds": 1})["stable"] is True
    commerce = engine.dispatch("checkout_readback", {"scope": scopes[0], "safe_item_nickname": "fixture"})
    assert commerce["subtotal"] == "$12.00" and commerce["total"] == "$14.00"
    emit("compatibility", paginated_text=True, bounded_stability=True, commerce_readback=True)
    try:
        engine.dispatch("selector_action", {"scope": scopes[0], "operation": "type", "selector": "#password", "text": "not-a-real-secret", "action_key": "protected-probe"})
    except ValueError:
        emit("protected-input", refused=True)
    else:
        raise AssertionError("protected input permitted")
    spec = importlib.util.spec_from_file_location("fixture_endpoint", "/opt/nest/firefox/bin/firefox-bridge-server.py")
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    viewer = endpoint.Server(("127.0.0.1", 0), endpoint.Handler)
    viewer.windows = engine
    threading.Thread(target=viewer.serve_forever, daemon=True).start()
    def owner(payload):
        request = urllib.request.Request(f"http://127.0.0.1:{viewer.server_port}/_nest/bridge/window/control",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Origin": "https://browser.eyrie",
                "Authorization": "Window " + bindings[0]["viewer"]})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    try:
        point = engine._evaluate(bindings[0]["context"], "(()=>{const r=document.querySelector('#password').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
        assert owner({"command": "input", "payload": {"kind": "pointer", **point}})["status"] == "ok"
        assert owner({"command": "input", "payload": {"kind": "key", "key": "x"}})["status"] == "ok"
        assert engine._evaluate(bindings[0]["context"], "document.querySelector('#password').value==='x'") is True
        assert engine._evaluate(bindings[1]["context"], "document.querySelector('#password').value===''") is True
        image = Image.open(io.BytesIO(base64.b64decode(owner({"command": "screenshot"})["png_base64"]))).convert("RGB")
        assert image.getpixel((image.width-20, image.height-20)) == (238, 17, 17)
        assert owner({"command": "input", "payload": {"kind": "scroll", "x": 20, "y": 100, "deltaX": 0, "deltaY": 500}})["status"] == "ok"
        deadline = time.monotonic() + 2
        while engine._evaluate(bindings[0]["context"], "scrollY") == 0 and time.monotonic() < deadline:
            time.sleep(.1)
        assert engine._evaluate(bindings[0]["context"], "scrollY") > 0
        assert engine._evaluate(bindings[1]["context"], "scrollY") == 0
        emit("owner-scroll", scoped=True, other_unchanged=True)
        emit("owner-viewer-http", bound_pixels=True, scoped_owner_input=True, protected_agent_input_refused=True, focus_unchanged=before == focus())
        viewer.bridge_token = "synthetic-canary-token"
        terminal = {"scope": scopes[0], "action": "close", "terminal_event_id": 1, "terminal_status": "completed"}
        for flag in ["closed", "already_closed"]:
            request = urllib.request.Request(f"http://127.0.0.1:{viewer.server_port}/_nest/bridge/v1",
                data=json.dumps({"command": "window_lifecycle", "payload": terminal}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + viewer.bridge_token})
            with urllib.request.urlopen(request, timeout=10) as response:
                receipt = json.load(response)
            assert receipt["status"] == "ok" and receipt[flag] is True
            assert all(receipt[k] == v for k, v in terminal.items())
            assert type(receipt["terminal_event_id"]) is int
        emit("broker-wire-acknowledgement", exact_terminal_identity=True, closed_then_already_closed=True)
    finally:
        viewer.shutdown()
        viewer.server_close()
    close = {"scope": scopes[0], "action": "close", "terminal_event_id": 1, "terminal_status": "completed"}
    assert engine.lifecycle(close)["already_closed"] is True
    assert len(engine._tree()) == 3
    assert any(c["context"] == root_extra for c in engine._tree())
    assert engine.acquire(scopes[1])["context"] == bindings[1]["context"]
    emit("terminal-close", root_preserved=True, root_tabs_preserved=2, other_preserved=True, remaining_contexts=3)
    assert before == focus(), "window operation stole the owner's X11 focus"
    emit("result", passed=True, focus_unchanged=True)
finally:
    if engine.browser:
        emit("final-native-tree", contexts=engine.browser._bidi_contexts())
        engine.browser.close()
        driver_request("DELETE", "/session/" + engine.state["controller"]["session"])
    server.shutdown()
