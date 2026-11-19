"""Window disposal is not request termination; uncertainty belongs to actions."""
import pytest
from test_firefox_windows import A, B, close, engine, windows  # noqa: F401


@pytest.mark.parametrize("producer", ["release", "expiry"])
def test_closed_nonterminal_window_can_be_used_again(engine, monkeypatch, producer):
    controller, native = engine
    first = controller.dispatch("tabs", {"scope": A, "action": "acquire"})
    original = dict(controller.state["windows"][A])
    other = dict(controller.acquire(B))
    controller.state["actions"]["unknown-old-input"] = {"state": "uncertain", "scope": A}
    if producer == "release":
        controller.dispatch("tabs", {"scope": A, "action": "release"})
    else:
        controller.state["windows"][A]["lease_expires_at"] = 1
        controller.sweep()
    assert controller.recovery(A)["next_action"] == "acquire"
    second = controller.dispatch("tabs", {"scope": A, "action": "acquire"})
    assert first["owner_window_url"] != second["owner_window_url"]
    assert controller.state["windows"][A]["context"] != original["context"]
    assert controller.state["actions"]["unknown-old-input"]["state"] == "uncertain"
    assert any(c["context"] == other["context"] for c in native.tree)
    assert len(native.tree) == 3


def test_deliberate_terminal_cleanup_still_fences_late_worker(engine):
    controller, native = engine
    controller.acquire(A)
    controller.lifecycle(close())
    with pytest.raises(RuntimeError):
        controller.acquire(A)
    assert controller.recovery(A)["next_action"] == "none"
    assert len(native.tree) == 1


def test_controller_restart_after_release_does_not_require_a_recovery_grant(engine, monkeypatch):
    controller, native = engine
    controller.acquire(A)
    controller.dispatch("tabs", {"scope": A, "action": "release"})
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "same", "epoch": controller.epoch}
    controller._save()
    monkeypatch.setattr(windows, "process_generation", lambda pid: "same")
    restarted = windows.Windows(controller.path, connect=lambda: native)
    assert restarted.dispatch("tabs", {"scope": A, "action": "acquire"})["status"] == "ok"
    assert len(native.tree) == 2


def test_browser_exit_allows_new_browsing_without_retiring_unknown_actions(engine, monkeypatch):
    import json
    controller, native = engine
    controller.acquire(A)
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "old", "epoch": controller.epoch}
    controller.state["actions"]["unknown"] = {"state": "started", "scope": A, "digest": "untouched"}
    controller._save()
    original = controller.path.read_bytes()
    monkeypatch.setattr(windows, "process_generation", lambda pid: "new")
    monkeypatch.setattr(windows, "driver_request", lambda *args: {"ready": True})
    native.tree = native.tree[:1]  # Actual old process has gone, not observer loss.
    resumed = windows.Windows(controller.path, connect=lambda: native)
    assert resumed.acquire(A)["state"] == "open"
    assert resumed.state["actions"] == json.loads(original)["actions"]
    assert next((controller.path.parent / "generation-history").glob("*.json")).read_bytes() == original
    assert not resumed.state.get("retired_action_keys")
    assert len(native.tree) == 2


def test_permission_error_is_not_proof_that_browser_exited(engine, monkeypatch):
    controller, native = engine
    controller.acquire(A)
    controller.state["controller"] = {"state": "ready", "pid": 123, "generation": "old", "epoch": controller.epoch}
    controller._save()
    def denied(pid):
        raise PermissionError("synthetic process metadata denial")
    monkeypatch.setattr(windows, "process_generation", denied)
    before = controller.path.read_bytes()
    with pytest.raises(PermissionError):
        controller.acquire(A)
    assert controller.path.read_bytes() == before
    assert len(native.tree) == 2
