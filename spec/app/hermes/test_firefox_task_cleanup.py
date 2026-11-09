"""Real resident-controller seams missed by terminal-only fixture coverage."""
import pytest

from test_firefox_windows import A, B, close, engine, windows  # noqa: F401


def test_lease_expiry_is_independent_of_worker_finally_and_preserves_renewed_scope(engine, monkeypatch):
    controller, native = engine
    now = [1000.0]
    monkeypatch.setattr(windows.time, "time", lambda: now[0])
    controller.dispatch("tabs", {"scope": A, "action": "acquire", "lease_seconds": 60})
    controller.dispatch("tabs", {"scope": B, "action": "acquire", "lease_seconds": 60})
    now[0] += 50
    controller.dispatch("tabs", {"scope": B, "action": "keep_open", "lease_seconds": 120})
    now[0] += 15
    controller.sweep()
    assert controller.state["windows"][A]["state"] == "closed"
    assert controller.state["windows"][B]["state"] == "open"
    assert len(native.tree) == 2
    assert native.tree[0]["context"] == "owner"
    now[0] += 120
    controller.sweep()
    assert len(native.tree) == 1


@pytest.mark.parametrize("lease", [True, 0, -1, 86401, "60", 1.5])
def test_invalid_lease_refuses_before_native_allocation(engine, lease):
    controller, native = engine
    with pytest.raises(ValueError):
        controller.dispatch("tabs", {"scope": A, "action": "acquire", "lease_seconds": lease})
    assert native.created == 0


def test_keep_open_requires_explicit_bounded_duration(engine):
    controller, native = engine
    with pytest.raises(ValueError):
        controller.dispatch("tabs", {"scope": A, "action": "keep_open"})
    assert native.created == 0


def test_janitor_does_not_age_legacy_or_owner_bindings(engine, monkeypatch):
    controller, native = engine
    record = controller.acquire(A)
    record.pop("lease_expires_at", None)
    monkeypatch.setattr(windows.time, "time", lambda: 10**12)
    controller.sweep()
    assert len(native.tree) == 2


def test_native_opener_descendants_close_but_unrelated_contexts_survive(engine):
    controller, native = engine
    root = controller.acquire(A).copy()
    other = controller.acquire(B).copy()
    native.tree.extend([
        {"context": "popup", "clientWindow": "popup-window", "originalOpener": root["context"]},
        {"context": "popup-tab", "clientWindow": "popup-window", "originalOpener": "popup"},
        {"context": "unrelated-popup", "clientWindow": "other-popup", "originalOpener": other["context"]},
    ])
    assert controller.lifecycle(close())["closed"]
    assert {c["context"] for c in native.tree} == {"owner", other["context"], "unrelated-popup"}


def test_explicit_release_then_terminal_attaches_exact_receipt(engine):
    controller, native = engine
    controller.acquire(A)
    controller.dispatch("tabs", {"scope": A, "action": "release"})
    assert controller.lifecycle(close())["already_closed"]
    assert controller.lifecycle(close())["already_closed"]
    assert len(native.tree) == 1


def test_explicit_release_closes_only_its_existing_native_context(engine):
    controller, native = engine
    owned = controller.acquire(A).copy()
    unrelated = controller.acquire(B).copy()
    controller.dispatch("tabs", {"scope": A, "action": "release"})
    assert not any(c["context"] == owned["context"] for c in native.tree)
    assert any(c["context"] == unrelated["context"] for c in native.tree)
    assert native.tree[0]["context"] == "owner"


def test_release_of_unallocated_scope_never_creates_a_native_window(engine):
    controller, native = engine
    controller.dispatch("tabs", {"scope": A, "action": "release"})
    assert native.created == 0
    assert [c["context"] for c in native.tree] == ["owner"]


def test_concurrent_renewal_wins_before_sweep_eligibility(engine, monkeypatch):
    import threading
    controller, native = engine
    now = [1000.0]
    monkeypatch.setattr(windows.time, "time", lambda: now[0])
    controller.dispatch("tabs", {"scope": A, "action": "acquire", "lease_seconds": 60})
    now[0] = 1061.0
    assert controller.cleanup_pending()
    entered = threading.Event()
    def sweeping():
        entered.set()
        controller.sweep()
    # Model a renewal committed between the advisory pending check and sweep.
    # operation() and dispatch() share the SAME reentrant controller lock.
    with controller.operation():
        thread = threading.Thread(target=sweeping)
        thread.start()
        assert entered.wait(1)
        controller.dispatch("tabs", {"scope": A, "action": "keep_open", "lease_seconds": 3600})
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert controller.state["windows"][A]["state"] == "open"
    assert len(native.tree) == 2
    assert not any(method == "browsingContext.close" for method, _ in native.calls)


def test_expiry_claim_fences_later_renewal_until_native_absence(engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    controller, native = engine
    record = controller.acquire(A)
    record["lease_expires_at"] = 1
    entered, proceed = threading.Event(), threading.Event()
    original = controller._close_owned
    def paused(record):
        entered.set()
        assert proceed.wait(2)
        return original(record)
    monkeypatch.setattr(controller, "_close_owned", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sweeping = pool.submit(controller.sweep)
        assert entered.wait(1)
        renewing = pool.submit(controller.dispatch, "tabs", {"scope": A, "action": "keep_open", "lease_seconds": 3600})
        assert not renewing.done()
        proceed.set()
        assert sweeping.result(timeout=2)[0]["closed"]
        with pytest.raises(RuntimeError):
            renewing.result(timeout=2)
    assert len(native.tree) == 1


def test_public_task_tool_producer_routes_release_to_its_native_binding(engine, monkeypatch, tmp_path):
    import json
    from test_secure_browser_firefox_ui import load_tool
    controller, native = engine
    module, _ = load_tool()
    module.CONTROL_MODE = "firefox-windows-v3"
    monkeypatch.setattr(module, "_session_env", lambda key: {
        "HERMES_KANBAN_TASK": "t_alpha", "HERMES_KANBAN_BOARD": "agent-requests"}.get(key, ""))
    module.BRIDGE_TOKEN_FILE = tmp_path / "synthetic-token"
    module.BRIDGE_TOKEN_FILE.write_text("synthetic-not-a-real-credential")

    class Reply:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            return self.body

    def transport(request, **kwargs):
        envelope = json.loads(request.data)
        return Reply(json.dumps(controller.dispatch(envelope["command"], envelope["payload"])).encode())

    monkeypatch.setattr(module.urllib.request.OpenerDirector, "open", lambda self, *args, **kwargs: transport(*args, **kwargs))
    assert json.loads(module.secure_browser_tab_lifecycle_tool({"action": "acquire", "lease_seconds": 60}))["status"] == "ok"
    other = controller.acquire(B).copy()
    result = json.loads(module.secure_browser_tab_lifecycle_tool({"action": "release", "workflow_id": B}))
    assert result["closed"]
    assert {c["context"] for c in native.tree} == {"owner", other["context"]}


def test_same_session_restart_reconciles_close_effect_without_resend(engine, monkeypatch):
    controller, native = engine
    record = controller.acquire(A)
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "same", "epoch": controller.epoch}
    controller._save()
    monkeypatch.setattr(windows, "process_generation", lambda pid: "same")
    original = native._bidi
    def lost_reply(method, params, **kwargs):
        result = original(method, params, **kwargs)
        if method == "browsingContext.close":
            raise OSError("fixture effect completed but response lost")
        return result
    monkeypatch.setattr(native, "_bidi", lost_reply)
    with pytest.raises(RuntimeError):
        controller.lifecycle(close())
    restarted = windows.Windows(controller.path, connect=lambda: native)
    assert restarted.lifecycle(close())["already_closed"]
    assert sum(method == "browsingContext.close" for method, _ in native.calls) == 1
    assert record["context"] not in {c["context"] for c in native.tree}


def test_native_generation_loss_refuses_cleanup_even_if_ids_look_identical(engine, monkeypatch):
    controller, native = engine
    controller.acquire(A)
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "old", "epoch": controller.epoch}
    controller._save()
    monkeypatch.setattr(windows, "process_generation", lambda pid: "new")
    restarted = windows.Windows(controller.path, connect=lambda: native)
    with pytest.raises(RuntimeError):
        restarted.lifecycle(close())
    assert len(native.tree) == 2
    assert not any(method == "browsingContext.close" for method, _ in native.calls)


def test_unproven_extra_context_does_not_starve_other_expired_scopes(engine, monkeypatch):
    controller, native = engine
    now = [1000.0]
    monkeypatch.setattr(windows.time, "time", lambda: now[0])
    root = controller.acquire(A)
    controller.acquire(B)
    native.tree.append({"context": "foreign", "clientWindow": root["window"]})
    now[0] = 3000.0
    for _ in range(4):
        controller.sweep()
        now[0] += 11
    assert controller.state["windows"][A]["cleanup_failures"] == 3
    assert controller.state["windows"][B]["state"] == "closed"
    assert not any(params.get("context") in {root["context"], "foreign"}
                   for method, params in native.calls if method == "browsingContext.close")


def test_terminal_cleanup_acknowledges_exact_already_absent_native_context(engine):
    controller, native = engine
    owned = controller.acquire(A).copy()
    unrelated = controller.acquire(B).copy()
    # Simulate a native close outside the controller, not URL/title inference.
    native.tree = [c for c in native.tree if c["context"] != owned["context"]]
    result = controller.lifecycle(close())
    assert result.get("closed") or result.get("already_closed")
    assert any(c["context"] == unrelated["context"] for c in native.tree)
    assert not any(method == "browsingContext.close" for method, _ in native.calls)


def test_terminal_cleanup_retries_exact_close_after_verified_still_present(engine, monkeypatch):
    controller, native = engine
    owned = controller.acquire(A).copy()
    controller.acquire(B)
    original = controller._call
    interrupted = False

    def call(method, params=None, **kwargs):
        nonlocal interrupted
        if method == "browsingContext.close" and not interrupted:
            interrupted = True
            raise RuntimeError("fixture close interrupted before native acknowledgement")
        return original(method, params, **kwargs)

    monkeypatch.setattr(controller, "_call", call)
    with pytest.raises(RuntimeError):
        controller.lifecycle(close())
    assert any(c["context"] == owned["context"] for c in native.tree)
    result = controller.lifecycle(close())
    assert result.get("closed") or result.get("already_closed")
    assert not any(c["context"] == owned["context"] for c in native.tree)
    assert native.tree[0]["context"] == "owner"
