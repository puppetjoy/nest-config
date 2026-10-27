"""HTTP window viewer authentication, scoped dispatch and no global fallback."""
import importlib.util
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request
import pytest
from unittest.mock import patch

from test_firefox_windows import A, B, Native, windows

ROOT = Path(__file__).resolve().parents[3]


def test_only_one_resident_process_owns_the_registry(tmp_path):
    spec = importlib.util.spec_from_file_location("window_endpoint_lock", ROOT / "files/firefox-browser/firefox-bridge-server.py")
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    first = endpoint.controller_lease(tmp_path / "controller.lock")
    try:
        with pytest.raises(RuntimeError, match="already owns"):
            endpoint.controller_lease(tmp_path / "controller.lock")
    finally:
        first.close()
    second = endpoint.controller_lease(tmp_path / "controller.lock")
    second.close()


def test_dead_controller_process_releases_exclusive_lease(tmp_path):
    import subprocess
    import sys
    source = ROOT / "files/firefox-browser/firefox-bridge-server.py"
    spec = importlib.util.spec_from_file_location("dead_controller_endpoint", source)
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    path = tmp_path / "controller.lock"
    child = subprocess.Popen([sys.executable, "-c",
        "import fcntl,sys; h=open(sys.argv[1],'a+'); fcntl.flock(h,fcntl.LOCK_EX); print('leased',flush=True); sys.stdin.read()", str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "leased"
        with pytest.raises(RuntimeError, match="already owns"):
            endpoint.controller_lease(path)
        child.kill()
        child.wait(timeout=5)
        recovered = endpoint.controller_lease(path)
        recovered.close()
    finally:
        child.kill() if child.poll() is None else None
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()


def test_owner_viewer_origin_capability_and_exact_scope(tmp_path):
    spec = importlib.util.spec_from_file_location("window_endpoint", ROOT / "files/firefox-browser/firefox-bridge-server.py")
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    native = Native()
    engine = windows.Windows(tmp_path / "windows.json", connect=lambda: native)
    first, second = engine.acquire(A), engine.acquire(B)
    endpoint.LOCK_PATH = tmp_path / "endpoint.lock"
    server = endpoint.Server(("127.0.0.1", 0), endpoint.Handler)
    server.windows = engine
    server.bridge_token = "synthetic-only-not-a-real-credential"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(body, cap=first["viewer"], origin="https://browser.eyrie"):
        request = urllib.request.Request(base + "/_nest/bridge/window/control", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Window " + cap, "Origin": origin})
        try:
            with urllib.request.urlopen(request, timeout=3) as reply:
                return reply.status, json.load(reply)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        with patch.object(engine, "dispatch", return_value={"png_base64": "synthetic-png"}) as dispatch:
            assert post({"command": "screenshot"}, origin="https://wrong.example")[0] == 403
            assert post({"command": "screenshot"}, cap="bad")[0] == 409
            assert post({"command": "screenshot", "scope": B})[0] == 409
            assert not dispatch.called
            assert post({"command": "screenshot"}) == (200, {"status": "ok", "png_base64": "synthetic-png"})
            dispatch.assert_called_once_with("screenshot", {"scope": A})
        with patch.object(engine, "owner_input", return_value={"status": "ok"}) as owner_input:
            body = {"command": "input", "payload": {"kind": "key", "key": "x"}}
            assert post(body, cap=second["viewer"])[0] == 200
            owner_input.assert_called_once_with(second["viewer"], body["payload"])
        with urllib.request.urlopen(base + "/_nest/bridge/window/") as reply:
            assert "frame-ancestors 'none'" in reply.headers["Content-Security-Policy"]
            assert reply.headers["Referrer-Policy"] == "no-referrer"
            assert reply.headers["Cache-Control"] == "no-store"
            assert b"Request Firefox page" in reply.read()
        with patch.object(endpoint.subprocess, "run", side_effect=AssertionError("global fallback forbidden")):
            request = urllib.request.Request(base + endpoint.API_PATH,
                data=json.dumps({"command": "snapshot", "payload": {}}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + server.bridge_token})
            with urllib.request.urlopen(request, timeout=3) as reply:
                assert json.load(reply)["status"] == "error"  # Missing immutable scope.
        assert native.created == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("code,outcome", [
    ("FIREFOX_TARGET_UNAVAILABLE", "not_started"),
    ("FIREFOX_OBSERVATION_UNAVAILABLE", "not_started"),
    ("FIREFOX_WINDOW_BUDGET", "not_started"),
    ("FIREFOX_NATIVE_OUTCOME_UNCERTAIN", "uncertain"),
    (None, "uncertain"),
])
def test_endpoint_preserves_preflight_vs_delivery_boundary(tmp_path, code, outcome):
    spec = importlib.util.spec_from_file_location("error_endpoint", ROOT / "files/firefox-browser/firefox-bridge-server.py")
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    endpoint.LOCK_PATH = tmp_path / "endpoint.lock"
    engine = windows.Windows(tmp_path / "windows.json")
    server = endpoint.Server(("127.0.0.1", 0), endpoint.Handler)
    server.windows = engine
    server.bridge_token = "synthetic-only-not-a-real-credential"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    error = windows.ControlError(code, "fixed safe refusal", outcome) if code else RuntimeError("private detail")
    try:
        with patch.object(engine, "dispatch", side_effect=error):
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}" + endpoint.API_PATH,
                data=json.dumps({"command": "selector_action", "payload": {"scope": A}}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + server.bridge_token})
            with urllib.request.urlopen(request, timeout=3) as reply:
                result = json.load(reply)
        assert result["error"] == (code or "FIREFOX_OUTCOME_UNCERTAIN")
        assert result["outcome"] == outcome
        assert "private detail" not in json.dumps(result)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
