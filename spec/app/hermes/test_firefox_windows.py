"""Same-session window identity, crash safety and exact broker receipt regressions."""
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("firefox_windows", ROOT / "files/firefox-browser/firefox_windows.py")
windows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(windows)
A = "kanban:agent-requests:t_alpha"
B = "kanban:agent-requests:t_beta"


class Native:
    def __init__(self):
        self.tree = [{"context": "owner", "clientWindow": "root", "url": "https://same.example/"}]
        self.calls = []
        self.fail_create = False
        self.created = 0

    def _bidi(self, method, payload, *, on_reply=None):
        self.calls.append((method, payload))
        if method == "browsingContext.getTree":
            return {"contexts": self.tree.copy()}
        if method == "browsingContext.create":
            self.created += 1
            cid = f"context-{self.created}"
            self.tree.append({"context": cid, "clientWindow": f"window-{self.created}", "url": "https://same.example/"})
            if self.fail_create:
                raise OSError("response lost after creation")
            if on_reply is not None:
                on_reply({"type": "success", "result": {"context": cid}})
            return {"context": cid}
        if method == "browsingContext.close":
            self.tree = [c for c in self.tree if c["context"] != payload["context"]]
            return {}
        raise AssertionError(method)


@pytest.fixture
def engine(tmp_path):
    native = Native()
    controller = windows.Windows(tmp_path / "windows.json", connect=lambda: native)
    return controller, native


def close(scope=A, event=42, status="completed"):
    return {"action": "close", "scope": scope, "terminal_event_id": event, "terminal_status": status}


def test_repeated_concurrent_acquire_same_session_distinct_windows(engine):
    controller, native = engine
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(controller.acquire, [A, B] * 10))
    assert native.created == 2
    assert result[0]["window"] != result[1]["window"]
    assert all(record["context"] == result[index % 2]["context"] for index, record in enumerate(result))
    assert not any(method == "browsingContext.activate" for method, _ in native.calls)
    assert native.tree[0]["clientWindow"] == "root"


def test_response_loss_and_restart_preserve_without_replacement(engine):
    controller, native = engine
    native.fail_create = True
    with pytest.raises(RuntimeError):
        controller.acquire(A)
    with pytest.raises(RuntimeError):
        controller.acquire(A)
    restarted = windows.Windows(controller.path, connect=lambda: native)
    for scope in (A, B):
        with pytest.raises(RuntimeError):
            restarted.acquire(scope)
    assert native.created == 1
    assert len(native.tree) == 2


def test_missing_binding_and_duplicate_urls_never_select_other_context(engine):
    controller, native = engine
    record = controller.acquire(A)
    controller.acquire(B)
    native.tree = [c for c in native.tree if c["context"] != record["context"]]
    with pytest.raises(RuntimeError):
        controller.acquire(A)
    assert native.created == 2
    assert not any(method == "browsingContext.close" for method, _ in native.calls)


def test_exact_terminal_closure_deduplicated_after_restart(engine):
    controller, native = engine
    controller.acquire(A)
    other = controller.acquire(B).copy()
    assert controller.lifecycle(close())["closed"] is True
    assert controller.lifecycle(close())["already_closed"] is True
    restarted = windows.Windows(controller.path, connect=lambda: native)
    assert restarted.lifecycle(close())["already_closed"] is True
    assert any(c["context"] == other["context"] for c in native.tree)
    assert native.tree[0]["context"] == "owner"
    assert len([m for m, _ in native.calls if m == "browsingContext.close"]) == 1
    with pytest.raises(RuntimeError):
        controller.acquire(A)
    with pytest.raises(RuntimeError):
        controller.lifecycle(close(event=43))


@pytest.mark.parametrize("status", ["blocked", "waiting", "review", "parked", "running", "failed_probe"])
def test_nonterminal_never_closes(engine, status):
    controller, native = engine
    controller.acquire(A)
    with pytest.raises(ValueError):
        controller.lifecycle(close(status=status))
    assert len(native.tree) == 2


def test_terminal_before_acquire_is_tombstoned(engine):
    controller, native = engine
    assert controller.lifecycle(close())["already_closed"] is True
    with pytest.raises(RuntimeError):
        controller.acquire(A)
    assert native.created == 0


def test_missing_terminal_identity_cannot_acknowledge_closed_scope(engine):
    controller, _ = engine
    controller.state["windows"][A] = {"state": "closed"}
    with pytest.raises(RuntimeError, match="exact terminal receipt"):
        controller.lifecycle(close())


def test_private_session_endpoint_is_literal_and_loopback_only():
    windows.validate_session_endpoint("session-fixture", "ws://127.0.0.1:9222/session/session-fixture")
    for session, endpoint in [
        ("../escape", "ws://127.0.0.1:9222/session/../escape"),
        ("fixture", "ws://wrong.example:9222/session/fixture"),
        ("fixture", "ws://127.0.0.1:9222/session/other"),
        ("fixture", "ws://127.0.0.1:9222/session/fixture?secret=value"),
    ]:
        with pytest.raises((ValueError, RuntimeError)):
            windows.validate_session_endpoint(session, endpoint)


def test_public_newline_is_shift_enter_not_submit(engine, monkeypatch):
    controller, _ = engine
    calls = []
    monkeypatch.setattr(controller, "_call", lambda method, payload: calls.append((method, payload)))
    controller._text_character("bound-context", "\n")
    assert calls == [("input.performActions", {"context": "bound-context", "actions": [{
        "type": "key", "id": "window-keyboard", "actions": [
            {"type": "keyDown", "value": "\ue008"},
            {"type": "keyDown", "value": "\ue007"},
            {"type": "keyUp", "value": "\ue007"},
            {"type": "keyUp", "value": "\ue008"},
        ]}]})]


@pytest.mark.parametrize("text,multiline", [("first\nsecond", False), ("first\tsecond", True), ("first\rsecond", True), ("\ue007", True)])
def test_invalid_public_control_input_is_rejected_before_action(engine, monkeypatch, text, multiline):
    controller, native = engine
    record = controller.acquire(A)
    monkeypatch.setitem(sys.modules, "secure_browser_local_bidi", SimpleNamespace(
        CdpSession=SimpleNamespace(_bidi_value=lambda value: {
            "protected": False, "editable": True, "multiline": multiline})))
    monkeypatch.setattr(controller, "_function", lambda *args, **kwargs: {"value": [("node", {"sharedId": "element"})]})
    monkeypatch.setattr(controller, "_summary", lambda cid: {"url": "https://same.example/"})
    with pytest.raises(ValueError, match="multiline|control characters"):
        controller._input("type", {"scope": A, "action_key": "invalid-control", "selector": "#draft", "text": text}, record, {})
    assert controller.state["actions"] == {}
    assert not any(method == "input.performActions" for method, _ in native.calls)


def test_foreign_context_moved_into_window_is_preserved(engine):
    controller, native = engine
    record = controller.acquire(A)
    native.tree.append({"context": "unproven", "clientWindow": record["window"]})
    with pytest.raises(RuntimeError):
        controller.lifecycle(close())
    assert not any(m == "browsingContext.close" for m, _ in native.calls)


def test_owner_window_never_closes_or_gets_replaced(engine):
    controller, native = engine
    assert controller.acquire("owner")["context"] == "owner"
    with pytest.raises(ValueError):
        controller.lifecycle(close(scope="owner"))
    assert native.created == 0


def test_exact_integer_event_and_scope_validation(engine):
    controller, _ = engine
    for scope in (None, "", "kanban::t_alpha", "kanban:agent-requests:t_alpha/../t_beta"):
        with pytest.raises(ValueError):
            controller.acquire(scope)
    for value in (True, "42", 0, -1):
        with pytest.raises(ValueError):
            controller.lifecycle(close(event=value))


def test_viewer_capability_has_only_its_own_scope(engine):
    controller, _ = engine
    a = controller.acquire(A)
    b = controller.acquire(B)
    assert controller.viewer_scope(a["viewer"]) == A
    assert controller.viewer_scope(b["viewer"]) == B
    with pytest.raises(ValueError):
        controller.viewer_scope("invalid")
    controller.lifecycle(close())
    with pytest.raises(ValueError):
        controller.viewer_scope(a["viewer"])


def test_owner_scroll_targets_only_capability_window(engine, monkeypatch):
    controller, _ = engine
    record = controller.acquire(A)
    controller.acquire(B)
    calls = []
    monkeypatch.setattr(controller, "_call", lambda method, payload: calls.append((method, payload)))
    monkeypatch.setattr(controller, "_resolve", lambda record: {})
    payload = {"kind": "scroll", "x": 20, "y": 40, "deltaX": 0, "deltaY": 500}
    assert controller.owner_input(record["viewer"], payload)["status"] == "ok"
    assert len(calls) == 1 and calls[0][1]["context"] == record["context"]
    assert calls[0][1]["actions"][0]["actions"][0]["deltaY"] == 500
    for value in [True, float("nan"), 2001, "500"]:
        with pytest.raises(ValueError):
            controller.owner_input(record["viewer"], {**payload, "deltaY": value})
    assert len(calls) == 1


def test_same_session_resume_preserves_exact_native_identity(engine, monkeypatch):
    controller, native = engine
    record = controller.acquire(A).copy()
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "same", "epoch": controller.epoch}
    controller._save()
    monkeypatch.setattr(windows, "process_generation", lambda pid: "same")
    restarted = windows.Windows(controller.path, connect=lambda: native)
    assert restarted.acquire(A)["context"] == record["context"]
    assert native.created == 1
    assert restarted.epoch == record["epoch"]
    monkeypatch.setattr(windows, "process_generation", lambda pid: "different")
    changed = windows.Windows(controller.path, connect=lambda: native)
    with pytest.raises(RuntimeError):
        changed.acquire(A)
    with pytest.raises(RuntimeError):
        changed.acquire(B)
    assert native.created == 1


def test_old_uncertain_journal_key_cannot_replay_in_new_window(tmp_path):
    key = "joyride-run11909-luna-test-rollback-type"
    legacy = {"action_keys": {key: {"delivery_state": "delivery_uncertain"}}}
    (tmp_path / "state.json").write_text(json.dumps(legacy))
    controller = windows.Windows(tmp_path / "windows.json")
    with pytest.raises(RuntimeError, match="preserved legacy"):
        controller._input("type", {"scope": A, "action_key": key, "text": "must not replay"}, {}, {})
    assert json.loads((tmp_path / "state.json").read_text()) == legacy
    assert controller.state["actions"] == {}


def test_adapter_scope_is_authoritative_not_workflow_or_payload(tmp_path, monkeypatch):
    from test_secure_browser_firefox_ui import load_tool
    from test_firefox_endpoint import Reply
    module, _ = load_tool()
    module.CONTROL_MODE = "firefox-windows-v3"
    module.BRIDGE_TOKEN_FILE = tmp_path / "token"
    module.BRIDGE_TOKEN_FILE.write_text("synthetic-test-credential-only")
    module._session_env = lambda key: ""
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "agent-requests")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_alpha")
    seen = []
    def send(_opener, request, **kw):
        seen.append(json.loads(request.data))
        return Reply(b'{"status":"ok"}')
    monkeypatch.setattr("urllib.request.OpenerDirector.open", send)
    module._bridge("snapshot", {"scope": B})
    assert seen[0]["payload"]["scope"] == A
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "")
    with pytest.raises(RuntimeError, match="authoritative"):
        module._bridge("snapshot", {})
    assert len(seen) == 1


def test_status_does_not_allocate_a_window(engine):
    controller, native = engine
    result = controller.dispatch("status", {"scope": A})
    assert result["scope_state"] == "unallocated"
    assert result["protocol"] == "firefox-windows-v3"
    assert controller.state["windows"] == {}
    assert native.created == 0


def test_returned_creation_identity_survives_failed_read_and_resume(engine, monkeypatch):
    controller, native = engine
    controller.acquire("owner")
    original = controller._tree
    def tree():
        if native.created:
            raise OSError("read failed after creation response")
        return original()
    monkeypatch.setattr(controller, "_tree", tree)
    with pytest.raises(OSError):
        controller.acquire(A)
    saved = json.loads(controller.path.read_text())["windows"][A]
    assert saved["state"] == "creating" and saved["context"] == "context-1"
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "same", "epoch": controller.epoch}
    controller._save()
    monkeypatch.setattr(windows, "process_generation", lambda pid: "same")
    resumed = windows.Windows(controller.path, connect=lambda: native)
    assert resumed.acquire(A)["context"] == "context-1"
    assert native.created == 1


def test_unknown_creation_is_explicitly_uncertain_and_never_replayed(engine):
    controller, native = engine
    native.fail_create = True
    with pytest.raises(windows.ControlError) as failed:
        controller.acquire(A)
    assert failed.value.outcome == "uncertain"
    with pytest.raises(windows.ControlError) as refused:
        controller.acquire(A)
    assert refused.value.code == "FIREFOX_CREATION_UNCERTAIN"
    assert native.created == 1


def test_owner_and_worker_lock_wait_is_bounded(engine):
    controller, _ = engine
    class Busy:
        def acquire(self, *, timeout):
            assert timeout == 5
            return False
        def release(self):
            raise AssertionError("unowned lock release")
    controller.lock = Busy()
    with pytest.raises(windows.ControlError) as refused:
        with controller.operation():
            raise AssertionError("operation started")
    assert refused.value.code == "FIREFOX_BUSY"
    assert refused.value.outcome == "not_started"


def test_observer_never_creates_or_ends_resident_session(monkeypatch):
    import contextlib
    import threading
    import time
    # The connector is private; inject only its transport, not its ownership logic.
    import types
    sent = []
    class Socket:
        closed = 0
        def send(self, raw):
            self.message = json.loads(raw)
            sent.append(self.message["method"])
        def recv(self, **kw):
            return json.dumps({"id": self.message["id"], "result": {}})
        def close(self):
            self.closed += 1
    sock = Socket()
    source = ROOT / "files/app/hermes/secure_browser_local_bidi.py"
    # Executable AST isolates optional websocket dependency in CI's minimal image.
    import ast
    tree = ast.parse(source.read_text())
    body: list[ast.stmt] = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))]
    namespace = {"contextlib": contextlib, "json": json, "os": __import__("os"), "threading": threading,
                 "time": time, "Any": object,
                 "websockets": types.SimpleNamespace(sync=types.SimpleNamespace(client=types.SimpleNamespace(connect=lambda *a, **kw: sock)))}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), namespace)
    monkeypatch.setenv("FIREFOX_CONTROL_PROTOCOL", "firefox-windows-v3")
    with pytest.raises(RuntimeError, match="RESIDENT_SESSION_REQUIRED"):
        namespace["CdpSession"]()
    assert sent == []
    browser = namespace["CdpSession"](websocket_url="ws://127.0.0.1:9222/session/owned")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: browser._bidi("browsingContext.getTree"), range(20)))
    browser.close()
    browser.close()
    assert sent == ["browsingContext.getTree"] * 20
    assert sock.closed == 1
    with pytest.raises(RuntimeError, match="closed"):
        browser._bidi("browsingContext.getTree")


def test_source_only_puppet_refresh_restores_adapter_and_support():
    import re
    manifest = (ROOT / "manifests/app/hermes/install.pp").read_text()
    for leaf in ["secure_browser_tool", "secure_browser_oauth_tool", "secure_browser_local_bidi", "secure_browser_bidi", "secure_browser_legacy_support", "firefox_ui_bridge"]:
        matched = re.search(r'file \{ "\$\{source_dir\}/tools/' + leaf + r'\.py":(.*?)\n  }', manifest, re.S)
        assert matched is not None, leaf
        resource = matched.group(1)
        assert "'hermes_source'" in resource, leaf
        assert "Vcsrepo[$source_dir]" in resource, leaf
    services = (ROOT / "manifests/lib/hermes.pp").read_text()
    for service in ["gateway", "dashboard"]:
        matched = re.search(r'exec \{ "restart_hermes_' + service + r'_\$\{profile\}":(.*?)refreshonly', services, re.S)
        assert matched is not None
        assert "'hermes_source'" in matched.group(1)
        assert "'hermes_firefox_bridge'" in matched.group(1)


@pytest.mark.parametrize("failure", [TimeoutError, KeyboardInterrupt])
def test_failed_native_call_closes_observer_without_replay(engine, failure, monkeypatch):
    controller, native = engine
    controller.acquire(A)
    called = []
    closed = []
    def fail(method, params):
        called.append(method)
        raise failure("synthetic transport interruption")
    monkeypatch.setattr(native, "_bidi", fail)
    monkeypatch.setattr(native, "close", lambda: closed.append(True), raising=False)
    expected = KeyboardInterrupt if failure is KeyboardInterrupt else windows.ControlError
    with pytest.raises(expected):
        controller._call("input.performActions", {"context": "context-1"})
    assert called == ["input.performActions"]
    assert closed == [True]
    assert controller.broken


def test_adapter_preserves_busy_vs_uncertain_without_replay(tmp_path, monkeypatch):
    import io
    import urllib.error
    from test_secure_browser_firefox_ui import load_tool
    module, _ = load_tool()
    module.CONTROL_MODE = "firefox-windows-v3"
    module.BRIDGE_TOKEN_FILE = tmp_path / "token"
    module.BRIDGE_TOKEN_FILE.write_text("synthetic-test-credential-only")
    module.CONTROLLER_STATE_DIR = tmp_path / "locks"
    module._session_env = lambda key: ""
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_alpha")
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "agent-requests")
    calls = []
    outcome = {"status": "error", "error": "FIREFOX_BUSY", "outcome": "not_started"}
    def send(*args, **kwargs):
        calls.append(True)
        raise urllib.error.HTTPError("https://fixture.invalid/", 409, "busy", {}, io.BytesIO(json.dumps(outcome).encode()))
    monkeypatch.setattr("urllib.request.OpenerDirector.open", send)
    result = json.loads(module.secure_browser_page_snapshot_tool({}))
    assert result["error"] == "FIREFOX_BUSY" and result["outcome"] == "not_started"
    outcome.clear()  # Unrecognized proxy error proves nothing about delivery.
    result = json.loads(module.secure_browser_page_snapshot_tool({}))
    assert result["outcome"] == "uncertain"
    assert len(calls) == 2


def test_legacy_clients_cannot_acquire_resident_protocol(monkeypatch):
    import ast
    import os
    source = ROOT / "files/app/hermes/secure_browser_legacy_support.py"
    tree = ast.parse(source.read_text())
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in {"CdpBridge", "CdpSession"}]
    namespace = {"os": os, "Any": object, "_free_port": lambda: 1234, "CDP_ENDPOINT_URL": "", "subprocess": __import__("subprocess")}
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(source), "exec", dont_inherit=True), namespace)
    monkeypatch.setenv("SECURE_BROWSER_CONTROL_MODE", "firefox-windows-v3")
    with pytest.raises(RuntimeError, match="RESIDENT_SESSION_REQUIRED"):
        namespace["CdpBridge"]().__enter__()
    with pytest.raises(RuntimeError, match="RESIDENT_SESSION_REQUIRED"):
        namespace["CdpSession"]("bidi+ws://127.0.0.1:9222/session")


def test_delivered_input_with_lost_response_is_not_replayed(engine, monkeypatch):
    controller, _ = engine
    record = controller.acquire(A)
    monkeypatch.setitem(sys.modules, "secure_browser_local_bidi", SimpleNamespace(
        CdpSession=SimpleNamespace(_bidi_value=lambda value: {"protected": False, "x": 10, "y": 20})))
    monkeypatch.setattr(controller, "_function", lambda *args, **kwargs: {"value": [("node", {"sharedId": "element"})]})
    monkeypatch.setattr(controller, "_summary", lambda cid: {"url": "https://same.example/"})
    sent = []
    def pointer(*args):
        sent.append(True)
        raise TimeoutError("input delivered but response lost")
    monkeypatch.setattr(controller, "_pointer", pointer)
    payload = {"scope": A, "action_key": "one-send-only", "selector": "#send"}
    with pytest.raises(TimeoutError):
        controller._input("click", payload, record, {})
    repeat = controller._input("click", payload, record, {})
    assert repeat["status"] == "delivery_uncertain"
    assert repeat["delivery"]["replay_blocked"] is True
    assert repeat["delivery"]["input_sent"] is False
    assert sent == [True]


def test_preflight_script_exception_is_not_started_and_has_no_journal_entry(engine, monkeypatch):
    controller, native = engine
    record = controller.acquire(A)
    monkeypatch.setitem(sys.modules, "secure_browser_local_bidi", SimpleNamespace(CdpSession=object))
    monkeypatch.setattr(controller, "_summary", lambda cid: {"url": "https://same.example/"})
    monkeypatch.setattr(controller, "_call", lambda *args: {"type": "exception", "exceptionDetails": {"text": "private page content"}})
    with pytest.raises(windows.ControlError) as refused:
        controller._input("click", {"scope": A, "action_key": "not-sent", "selector": "#missing"}, record, {})
    assert refused.value.code == "FIREFOX_TARGET_UNAVAILABLE"
    assert refused.value.outcome == "not_started"
    assert "private page content" not in str(refused.value)
    assert controller.state["actions"] == {}
    assert not any(m == "input.performActions" for m, _ in native.calls)
    # A later field failure after the journal boundary must remain uncertain.
    with pytest.raises(RuntimeError) as failed:
        controller._function(record["context"], windows.FIELD, [])
    assert not isinstance(failed.value, windows.ControlError)


def test_native_budget_refuses_before_reservation_and_preserves_unknown_windows(engine):
    controller, native = engine
    controller.acquire("owner")
    native.tree.extend({"context": f"foreign-{n}", "clientWindow": f"foreign-{n}"} for n in range(11))
    before = json.loads(controller.path.read_text())
    with pytest.raises(windows.ControlError) as refused:
        controller.acquire(A)
    assert refused.value.code == "FIREFOX_WINDOW_BUDGET"
    assert refused.value.outcome == "not_started"
    assert json.loads(controller.path.read_text()) == before
    assert native.created == 0
    assert not any(m == "browsingContext.close" for m, _ in native.calls)


def test_read_only_script_exception_does_not_claim_input_uncertainty(engine, monkeypatch):
    controller, _ = engine
    monkeypatch.setitem(sys.modules, "secure_browser_bidi", SimpleNamespace())
    monkeypatch.setattr(controller, "_call", lambda *args: {"type": "exception"})
    with pytest.raises(windows.ControlError) as refused:
        controller._evaluate("context", "fixed read", read_only=True)
    assert refused.value.code == "FIREFOX_OBSERVATION_UNAVAILABLE"
    assert refused.value.outcome == "not_started"
    with pytest.raises(RuntimeError) as failed:
        controller._evaluate("context", "post-input read")
    assert not isinstance(failed.value, windows.ControlError)


@pytest.mark.parametrize("code", ["FIREFOX_TARGET_UNAVAILABLE", "FIREFOX_OBSERVATION_UNAVAILABLE", "FIREFOX_WINDOW_BUDGET"])
def test_adapter_retains_preinput_refusals_without_retry(tmp_path, monkeypatch, code):
    from test_secure_browser_firefox_ui import load_tool
    from test_firefox_endpoint import Reply
    module, _ = load_tool()
    module.CONTROL_MODE = "firefox-windows-v3"
    module.BRIDGE_TOKEN_FILE = tmp_path / "token"
    module.BRIDGE_TOKEN_FILE.write_text("synthetic-test-credential-only")
    module._session_env = lambda key: ""
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_alpha")
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "agent-requests")
    calls = []
    def send(*args, **kwargs):
        calls.append(True)
        return Reply(json.dumps({"status": "error", "error": code, "outcome": "not_started"}).encode())
    monkeypatch.setattr("urllib.request.OpenerDirector.open", send)
    result = json.loads(module.secure_browser_page_snapshot_tool({}))
    assert result["error"] == code and result["outcome"] == "not_started"
    assert calls == [True]
