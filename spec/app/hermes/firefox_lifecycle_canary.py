"""Disposable Firefox native lifecycle checks. No owner profile or network.

Run inside a managed image with FIREFOX_CONTROL_PROTOCOL=firefox-windows-v3.
The wire timeout is injected before reading a REAL Firefox response, not by
inventing a protocol response. Unknown fixture windows survive until teardown.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, "/opt/nest/firefox/bin")
from firefox_windows import ControlError, Windows


def emit(stage, **facts):
    print(json.dumps({"stage": stage, **facts}), flush=True)


engine = Windows("/tmp/nest-firefox/lifecycle-canary.json")
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
for extra in engine._tree()[1:]:
    engine._call("browsingContext.close", {"context": extra["context"], "promptUnload": False})
root = engine.acquire("owner").copy()
scopes = ["kanban:lifecycle-fixture:t_alpha", "kanban:lifecycle-fixture:t_beta"]
wire = engine.browser.ws
send, recv = wire.send, wire.recv
delayed = False


def sending(raw):
    global delayed
    if json.loads(raw)["method"] == "browsingContext.create":
        delayed = True
    return send(raw)


def receiving(**kwargs):
    global delayed
    if delayed:
        delayed = False
        raise TimeoutError("fixture caller deadline before real native reply")
    return recv(**kwargs)


wire.send, wire.recv = sending, receiving
try:
    engine.acquire(scopes[0])
except ControlError as exc:
    assert exc.outcome == "uncertain"
else:
    raise AssertionError("wire timeout not exercised")
assert engine.dispatch("tabs", {"scope": scopes[0], "action": "recover"})["recovery"]["recovery_state"] == "verified"
wire.send, wire.recv = send, recv
first = engine.acquire(scopes[0]).copy()
assert type(first["native_receipt_id"]) is int
with ThreadPoolExecutor(max_workers=2) as pool:
    bindings = list(pool.map(engine.acquire, scopes * 3))
assert bindings[0]["window"] != bindings[1]["window"]
assert len(engine._tree()) == 3
engine.browser.close()
engine = Windows(engine.path)
assert engine.acquire(scopes[0])["context"] == first["context"]
assert engine.acquire("owner")["window"] == root["window"]
emit("late-native-receipt", recovered=True, duplicate_creation=False, controller_reconnect=True, concurrent_scope_isolation=True)

# An already-lost receipt cannot be reconstructed from URL/tree subtraction.
# Exercise the separately authorized, one-shot local operator recovery.
unknown = "kanban:lifecycle-fixture:t_unknown"
original = engine.browser._bidi


def lose_receipt(method, params=None, *, on_reply=None):
    result = original(method, params, on_reply=None if method == "browsingContext.create" else on_reply)
    if method == "browsingContext.create":
        raise OSError("fixture transport lost after possible creation")
    return result


engine.browser._bidi = lose_receipt
try:
    engine.acquire(unknown)
except ControlError:
    pass
else:
    raise AssertionError("missing receipt not exercised")
engine = Windows(engine.path)
before = json.loads(engine.path.read_text())["windows"][unknown]
grant = {"scope": unknown, "authorization": "ar-native-fixture", "epoch": engine.epoch,
         "creation_id": before["creation_id"], "journal_sha256": hashlib.sha256(engine.path.read_bytes()).hexdigest(),
         "expires_at": int(time.time()) + 300}
engine.authorize_creation_recovery(grant)
replacement = engine.acquire(unknown).copy()
engine.authorize_creation_recovery(grant)
assert engine.acquire(unknown)["context"] == replacement["context"]
assert engine.state["creation_recoveries"][unknown]["original"] == before
assert len(engine._tree()) == 5
for scope in scopes + [unknown]:
    receipt = {"action": "close", "scope": scope, "terminal_event_id": 1, "terminal_status": "completed"}
    assert engine.lifecycle(receipt)["closed"] is True
    assert engine.lifecycle(receipt)["already_closed"] is True
assert len(engine._tree()) == 2
assert engine.acquire("owner")["context"] == root["context"]
emit("one-shot-missing-receipt-recovery", old_provenance_preserved=True, original_unknown_window_preserved=True,
     owner_preserved=True, exact_terminal_cleanup=True, no_input_replayed=True)
