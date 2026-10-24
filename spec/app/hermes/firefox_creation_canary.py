"""Disposable native Firefox fault injection. Never run against the owner profile.

Uses no external network, owner mounts, credentials, chat or fake active ARs.
The unidentifiable fixture window is deliberately preserved until the disposable
container exits. Tree subtraction is NOT ownership proof.
"""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, "/opt/nest/firefox/bin")
from firefox_windows import ControlError, Windows


def emit(stage, **facts):
    print(json.dumps({"stage": stage, **facts}), flush=True)


engine = Windows("/tmp/nest-firefox/creation-canary.json")
# Bounded startup readiness and first-run extension settling, fixture only.
deadline = time.monotonic() + 40
while True:
    try:
        tree = engine._tree()
        break
    except ControlError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(.2)
        engine = Windows(engine.path)
time.sleep(2)
tree = engine._tree()
for extra in tree[1:]:
    engine._call("browsingContext.close", {"context": extra["context"], "promptUnload": False})
root = engine.acquire("owner").copy()
scopes = {name: "kanban:ar2085-fixture:t_" + name for name in ["before", "after", "rejected"]}
for name in ["before", "after", "rejected"]:
    engine._tree()
    original = engine.browser._bidi
    def exchange(method, params=None, *, on_reply=None):
        if method != "browsingContext.create":
            return original(method, params, on_reply=on_reply)
        if name == "rejected":
            return original(method, {"type": "invalid-fixture-type"}, on_reply=on_reply)
        result = original(method, params, on_reply=on_reply if name == "after" else None)
        raise TimeoutError("fixture loses caller response after native creation")
    engine.browser._bidi = exchange
    try:
        engine.acquire(scopes[name])
    except ControlError as exc:
        emit("native-fault", boundary=name, error=exc.code, outcome=exc.outcome)
        assert exc.code == ("FIREFOX_CREATE_REJECTED" if name == "rejected" else "FIREFOX_NATIVE_OUTCOME_UNCERTAIN")
    else:
        raise AssertionError("fault was not exercised")
    engine = Windows(engine.path)
    before = len(engine._tree())
    for _ in range(3):
        result = engine.dispatch("tabs", {"scope": scopes[name], "action": "recover"})
        recovery = result["recovery"]
        assert recovery["input_replay_allowed"] is False
        assert recovery["retry_allowed"] is False
        expected = {"before": "engineering_repair_required", "after": "verified", "rejected": "engineering_repair_required"}[name]
        assert recovery["recovery_state"] == expected
    assert len(engine._tree()) == before
    assert engine.acquire("owner")["context"] == root["context"]
    emit("finite-recovery", boundary=name, recovery_state=recovery["recovery_state"], repeated=3, no_duplicate_windows=True, root_preserved=True)
    if name != "before":
        receipt = {"action": "close", "scope": scopes[name], "terminal_event_id": 1, "terminal_status": "completed"}
        assert engine.lifecycle(receipt)["status"] == "ok"
        assert engine.lifecycle(receipt)["already_closed"] is True
emit("completed", unidentifiable_fixture_window_preserved=True, native_replies_used=True)
