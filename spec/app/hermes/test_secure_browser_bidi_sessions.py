#!/usr/bin/env python3
"""Regression checks for bounded Firefox BiDi session lifecycles."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import sys
import tempfile
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURE_BROWSER_TOOL = REPO_ROOT / "files/app/hermes/secure_browser_tool.py"
MSC_REGISTRATION_URL = "https://www.mscdirect.com/ui/identity/registration"
PROCESS_MODULE: Any = None
PROCESS_EVENTS: Any = None
PROCESS_START: Any = None


class DummyRegistry:
    def register(self, **_kwargs: Any) -> None:
        return None


def load_tool_module(lock_path: Path, state_path: Path):
    websockets_module = types.ModuleType("websockets")
    websockets_sync_module = types.ModuleType("websockets.sync")
    websockets_client_module = types.ModuleType("websockets.sync.client")
    setattr(websockets_client_module, "connect", lambda *_args, **_kwargs: None)
    setattr(websockets_sync_module, "client", websockets_client_module)
    setattr(websockets_module, "sync", websockets_sync_module)
    sys.modules.setdefault("websockets", websockets_module)
    sys.modules.setdefault("websockets.sync", websockets_sync_module)
    sys.modules.setdefault("websockets.sync.client", websockets_client_module)

    tools_module = types.ModuleType("tools")
    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", DummyRegistry())
    sys.modules.setdefault("tools", tools_module)
    sys.modules["tools.registry"] = registry_module

    spec = importlib.util.spec_from_file_location("secure_browser_bidi_sessions_under_test", SECURE_BROWSER_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    setattr(module, "BIDI_SESSION_LOCK_PATH", str(lock_path))
    setattr(module, "OWNERSHIP_STATE_PATH", str(state_path))
    setattr(module, "BROWSER_OWNER", "msc-registration-test")
    setattr(module, "AUDIT_LOG", str(lock_path.with_suffix(".audit.log")))
    return module


class FakeBridge:
    def __enter__(self) -> str:
        return "https://browser-cdp.eyrie"

    def __exit__(self, *_exc: object) -> None:
        return None


class ConcurrentFakeSession:
    guard = threading.Lock()
    active = 0
    maximum_active = 0
    created = 0
    closed = 0

    def __init__(self, _websocket_url: str, cdp_url: str | None = None) -> None:
        self.protocol = "bidi"
        self.cdp_url = cdp_url
        with self.guard:
            type(self).active += 1
            type(self).created += 1
            type(self).maximum_active = max(type(self).maximum_active, type(self).active)

    def close(self) -> None:
        with self.guard:
            type(self).active -= 1
            type(self).closed += 1


class FailingNewSessionWebSocket:
    def __init__(self) -> None:
        self.closed = False

    def send(self, _payload: str) -> None:
        return None

    def recv(self, timeout: int = 10) -> str:
        del timeout
        return json.dumps({"id": 1, "type": "error", "error": "session not created", "message": "Maximum number of active sessions"})

    def close(self) -> None:
        self.closed = True


def _configure_msc_operation_fakes(module: Any) -> None:
    module.CdpBridge = FakeBridge
    module.CdpSession = ConcurrentFakeSession
    module._browser_ws_url = lambda _url: "bidi+wss://browser-cdp.eyrie:443/session"
    module._first_page_target = lambda _browser: "msc-registration-tab"
    module._owned_page_info = lambda _browser: {"id": "msc-registration-tab", "url": MSC_REGISTRATION_URL, "title": "Create an MSC Account"}
    module._attach = lambda _browser, target_id: target_id
    module._page_candidates = lambda _browser: [{"id": "msc-registration-tab", "url": MSC_REGISTRATION_URL, "title": "Create an MSC Account"}]
    module._select_post_click_owner_page = lambda *_args, **_kwargs: {"id": "msc-registration-tab", "url": MSC_REGISTRATION_URL, "title": "Create an MSC Account"}
    module._store_owner_target = lambda *_args, **_kwargs: None
    module._audit = lambda *_args, **_kwargs: None

    def fake_evaluate(_browser: Any, _session_id: str, expression: str) -> Any:
        time.sleep(0.025)
        if expression == "location.href":
            return MSC_REGISTRATION_URL
        if expression == "document.title":
            return "Create an MSC Account"
        if expression == module.PAGE_SNAPSHOT_JS.replace("__MAX_TEXT_CHARS__", str(module.MAX_TEXT_CHARS)).replace("__MAX_LINKS__", str(module.MAX_LINKS)):
            return {
                "url": MSC_REGISTRATION_URL,
                "page_title": "Create an MSC Account",
                "text": "Account Type Personal Business",
                "interactive": [{"selector": "#select-input", "text": "Account Type"}],
            }
        if expression == module.CLICK_JS.replace("__SELECTOR__", module._json_literal("#select-input")):
            return {"clicked": True, "element_text": "Account Type"}
        if "document.querySelector" in expression and "innerText" in expression:
            return "Account Type"
        if "const value =" in expression:
            return ["Personal", "Business"]
        return None

    module._evaluate = fake_evaluate


def test_constructor_closes_websocket_when_session_new_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "bidi.lock", Path(tmpdir) / "tabs.json")
        websocket = FailingNewSessionWebSocket()
        module.websockets.sync.client.connect = lambda *_args, **_kwargs: websocket
        try:
            module.CdpSession("bidi+wss://browser-cdp.eyrie:443/session")
        except RuntimeError as exc:
            assert "Maximum number of active sessions" in str(exc)
        else:
            raise AssertionError("session.new failure must propagate")
        assert websocket.closed, "failed session.new must close its WebSocket"


def test_msc_snapshot_query_and_selector_click_share_one_bidi_session_slot() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "bidi.lock", Path(tmpdir) / "tabs.json")
        _configure_msc_operation_fakes(module)
        ConcurrentFakeSession.active = 0
        ConcurrentFakeSession.maximum_active = 0
        ConcurrentFakeSession.created = 0
        ConcurrentFakeSession.closed = 0

        operations = [
            lambda: module._page_snapshot(),
            lambda: module._query("document.title"),
            lambda: module._click("#select-input", "Open the non-sensitive Account Type selector", "select_option"),
        ] * 4
        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            results = list(executor.map(lambda operation: operation(), operations))

        assert {result["operation"] for result in results} == {"page_snapshot", "query", "click"}
        assert all(MSC_REGISTRATION_URL in json.dumps(result) or result["operation"] == "query" for result in results)
        assert ConcurrentFakeSession.maximum_active == 1
        assert ConcurrentFakeSession.active == 0
        assert ConcurrentFakeSession.created == ConcurrentFakeSession.closed == len(operations)


def test_screenshot_uses_shared_browser_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "bidi.lock", Path(tmpdir) / "tabs.json")
        seen: list[Any] = []
        setattr(module, "_with_browser", lambda fn: (seen.append(fn), {"locked": True})[1])
        result = module._screenshot()
        assert result == {"locked": True}
        assert len(seen) == 1


def _process_lock_worker() -> None:
    assert PROCESS_MODULE is not None and PROCESS_EVENTS is not None and PROCESS_START is not None
    PROCESS_START.wait()

    def critical(_browser: Any) -> dict[str, Any]:
        started = time.monotonic()
        PROCESS_EVENTS.append(("start", multiprocessing.current_process().pid, started))
        time.sleep(0.12)
        ended = time.monotonic()
        PROCESS_EVENTS.append(("end", multiprocessing.current_process().pid, ended))
        return {"status": "ok"}

    PROCESS_MODULE._with_browser(critical)


def test_bidi_lifecycle_lock_serializes_across_processes() -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        return
    global PROCESS_MODULE, PROCESS_EVENTS, PROCESS_START
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_tool_module(Path(tmpdir) / "bidi.lock", Path(tmpdir) / "tabs.json")
        setattr(module, "CdpBridge", FakeBridge)
        setattr(module, "CdpSession", ConcurrentFakeSession)
        setattr(module, "_browser_ws_url", lambda _url: "bidi+wss://browser-cdp.eyrie:443/session")
        context = multiprocessing.get_context("fork")
        with context.Manager() as manager:
            PROCESS_MODULE = module
            PROCESS_EVENTS = manager.list()
            PROCESS_START = context.Event()
            processes = [context.Process(target=_process_lock_worker) for _ in range(3)]
            for process in processes:
                process.start()
            PROCESS_START.set()
            for process in processes:
                process.join(5)
                assert process.exitcode == 0
            events = list(PROCESS_EVENTS)

        intervals: dict[int, dict[str, float]] = {}
        for kind, pid, stamp in events:
            intervals.setdefault(pid, {})[kind] = stamp
        ordered = sorted((value["start"], value["end"]) for value in intervals.values())
        assert len(ordered) == 3
        assert all(previous[1] <= current[0] for previous, current in zip(ordered, ordered[1:])), ordered


if __name__ == "__main__":
    test_constructor_closes_websocket_when_session_new_fails()
    test_msc_snapshot_query_and_selector_click_share_one_bidi_session_slot()
    test_screenshot_uses_shared_browser_lifecycle()
    test_bidi_lifecycle_lock_serializes_across_processes()
    print("secure browser BiDi session regression checks passed")
