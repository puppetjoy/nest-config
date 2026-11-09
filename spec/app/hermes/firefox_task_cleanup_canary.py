"""Disposable native Firefox cleanup acceptance; no owner mounts/network.

Run only in a fresh managed Firefox/Kasm container, no bridge service credential.
The fixture uses native client/dispatch producers and real page-created popups.
Clock-controlled lease expiry is distinct from real periodic server-loop proof.
"""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import quote

sys.path.insert(0, "/opt/nest/firefox/bin")
from firefox_windows import Windows, driver_request


def emit(stage, **facts):
    print(json.dumps({"stage": stage, **facts}), flush=True)


def cpu_ticks():
    total = {}
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            try:
                stat = (path / "stat").read_text().rsplit(") ", 1)[1].split()
                total[(path.name, stat[19])] = int(stat[11]) + int(stat[12])
            except (OSError, ValueError):
                pass
    return total


def cpu_sample(seconds=2):
    start, ticks = time.monotonic(), cpu_ticks()
    time.sleep(seconds)
    after = cpu_ticks()
    delta = sum(max(0, value - ticks[identity]) for identity, value in after.items() if identity in ticks)
    return delta / os.sysconf("SC_CLK_TCK") / (time.monotonic() - start) * 100


# Read-only startup gating BEFORE reserving the sole native session.
end = time.monotonic() + 45
while True:
    try:
        assert driver_request("GET", "/status")["ready"] is True
        with socket.create_connection(("127.0.0.1", 2828), timeout=1):
            pass
        break
    except (OSError, AssertionError):
        if time.monotonic() > end:
            raise
        time.sleep(.2)
# Allow the fresh extension's one-time browser-start welcome producer to finish
# before baseline capture; it has no native opener and must NOT be adopted.
time.sleep(12)
engine = Windows("/tmp/nest-firefox/task-cleanup-canary.json")
time.sleep(2)
# Fresh fixture profile only: retire browser first-run/extension welcome tabs
# before declaring its sole synthetic owner baseline. Never run on production.
for extra in engine._tree()[1:]:
    engine._call("browsingContext.close", {"context": extra["context"], "promptUnload": False})
root = engine.acquire("owner").copy()
baseline = {c["context"] for c in engine._tree()}


def scope(name):
    return "kanban:cleanup-fixture:t_" + name


def acquire(name, lease=1800):
    value = scope(name)
    engine.dispatch("tabs", {"scope": value, "action": "acquire", "lease_seconds": lease})
    return value, engine.state["windows"][value]


def terminal(value, event, status="completed"):
    receipt = {"action": "close", "scope": value, "terminal_event_id": event, "terminal_status": status}
    result = engine.lifecycle(receipt)
    assert result.get("closed") or result.get("already_closed")
    assert engine.lifecycle(receipt)["already_closed"]


# Real synthetic, continuously rendered frames; no private app/session read.
html = """<!doctype html><title>Synthetic cleanup fixture</title>
<canvas id=c width=640 height=480></canvas><script>
let frames=0; const ctx=c.getContext('2d');
function draw(){frames++;ctx.fillStyle=`hsl(${frames%360},80%,50%)`;
ctx.fillRect(0,0,640,480);requestAnimationFrame(draw)}draw();
</script>"""
idle_before = cpu_sample()
active = []
for index in range(4):
    value, record = acquire("render" + str(index))
    engine._call("browsingContext.navigate", {"context": record["context"], "url": "data:text/html," + quote(html), "wait": "complete"})
    active.append((value, record.copy()))
time.sleep(1)
loaded_cpu = cpu_sample()
frames = [engine._evaluate(record["context"], "frames") for _, record in active]
assert all(value > 0 for value in frames)
for index, (value, _) in enumerate(active):
    terminal(value, index + 10)
assert {c["context"] for c in engine._tree()} == baseline
idle_after = cpu_sample()
emit("render-cleanup", workflows=4, real_frames=frames, cpu_percent_before=round(idle_before, 2),
     cpu_percent_loaded=round(loaded_cpu, 2), cpu_percent_after=round(idle_after, 2),
     native_contexts_at_baseline=True,     cpu_boundary="same-PID-and-birth surviving processes per interval in disposable container; not production Muse")

# Native opener identity across observer reconstruction, not fixture dictionaries.
value, record = acquire("popup")
engine._call("browsingContext.navigate", {"context": record["context"], "url": "data:text/html,<title>Popup fixture</title>", "wait": "complete"})
engine._evaluate(record["context"], "window.open('about:blank','_blank'); true")
tree = engine._tree()
popups = [c for c in tree if c.get("originalOpener") == record["context"]]
assert len(popups) == 1, "native Firefox must expose originalOpener for cleanup"
engine.browser.close()
engine = Windows(engine.path)
terminal(value, 20)
assert {c["context"] for c in engine._tree()} == baseline
emit("native-popup", native_opener_proven=True, same_session_restart=True, exact_cleanup=True)

# Sequential task-like jobs never accumulate; cancellation shares exact receipt.
for index in range(4):
    value, _ = acquire("sequential" + str(index))
    terminal(value, index + 30, "cancelled" if index % 2 else "completed")
    assert {c["context"] for c in engine._tree()} == baseline
value, _ = acquire("release")
assert engine.dispatch("tabs", {"scope": value, "action": "release"})["closed"]
terminal(value, 40)
assert {c["context"] for c in engine._tree()} == baseline

# Independent server loop expires a departed producer's real context with no
# subsequent task/model/readback call. Shorten only the fixture's durable clock.
value, record = acquire("departed", 60)
other, retained = acquire("renewed", 60)
engine.dispatch("tabs", {"scope": other, "action": "keep_open", "lease_seconds": 3600})
record["lease_expires_at"] = time.time() - 1
engine._save()
engine.browser.close()
engine = Windows(engine.path)
spec = importlib.util.spec_from_file_location("cleanup_endpoint", "/opt/nest/firefox/bin/firefox-bridge-server.py")
endpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endpoint)
server = endpoint.Server(("127.0.0.1", 0), endpoint.Handler)
server.windows = engine
thread = threading.Thread(target=server.serve_forever, daemon=True)
started = time.monotonic()
thread.start()
try:
    # Wait on the durable result, no dispatch/sweep call from the task.
    end = started + 8
    while json.loads(engine.path.read_text())["windows"][value]["state"] != "closed":
        if time.monotonic() > end:
            raise AssertionError("periodic cleanup exceeded fixture bound")
        time.sleep(.1)
    elapsed = time.monotonic() - started
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
assert engine.state["windows"][other]["state"] == "open"
terminal(other, 41)
assert {c["context"] for c in engine._tree()} == baseline
assert engine.acquire("owner")["window"] == root["window"]
emit("periodic-expiry", cleanup_seconds=round(elapsed, 3), no_finally_or_followup_tool=True,
     renewed_long_task_preserved=True, owner_preserved=True, final_native_contexts=len(baseline))
