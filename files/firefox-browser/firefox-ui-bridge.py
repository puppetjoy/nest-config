#!/usr/bin/env python3
"""OS/accessibility control for the persistent browser.eyrie Firefox desktop.

This process deliberately has no WebDriver, Marionette, BiDi, CDP, extension,
profile-database, cookie, or page-script access. It observes Firefox through
AT-SPI and X11 screenshots and sends input through XTest via xdotool.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit, urlunsplit

DISPLAY = os.environ.get("DISPLAY", ":1")
STATE_DIR = Path(os.environ.get("FIREFOX_UI_STATE_DIR", "/home/kasm-user/.local/state/nest-firefox-ui"))
STATE_PATH = STATE_DIR / "state.json"
LOCK_PATH = STATE_DIR / "state.lock"
SESSION_ENV_PATH = Path(os.environ.get("FIREFOX_UI_SESSION_ENV", "/tmp/nest-firefox/session.env"))
DEFAULT_HARD_TAB_CAP = int(os.environ.get("FIREFOX_UI_HARD_TAB_CAP", "12"))
DEFAULT_LEASE_SECONDS = int(os.environ.get("FIREFOX_UI_LEASE_SECONDS", "7200"))
MAX_NODES = int(os.environ.get("FIREFOX_UI_MAX_NODES", "350"))
MAX_NAME = 240
SENSITIVE_RE = re.compile(
    r"password|passcode|one[- ]?time|security code|cvv|cvc|card number|account number|routing number|secret|token|private key|recovery code",
    re.IGNORECASE,
)
INTERACTIVE_ROLES = {
    "push button", "button", "check box", "combo box", "entry", "link",
    "menu item", "page tab", "radio button", "slider", "spin button",
    "text", "toggle button",
}


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _run(argv: list[str], *, input_text: str | None = None, timeout: float = 20) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        input=None if input_text is None else input_text.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env={**os.environ, "DISPLAY": DISPLAY},
    )


def _xdotool(*args: str, timeout: float = 20) -> str:
    result = _run(["xdotool", *args], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"xdotool failed ({result.returncode}): {result.stderr.decode(errors='replace')[:500]}")
    return result.stdout.decode(errors="replace").strip()


def _load_session_environment() -> None:
    if not SESSION_ENV_PATH.exists():
        return
    for raw in SESSION_ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = raw.partition("=")
        if separator and key in {"DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS"}:
            os.environ[key] = value


def _firefox_window_id() -> str:
    result = _run(["xdotool", "search", "--onlyvisible", "--classname", "Navigator"])
    ids = result.stdout.decode().split()
    if not ids:
        raise RuntimeError("no visible Firefox Navigator window")
    best = ""
    best_area = -1
    for window_id in ids:
        geometry = _run(["xdotool", "getwindowgeometry", "--shell", window_id]).stdout.decode()
        values = dict(line.split("=", 1) for line in geometry.splitlines() if "=" in line)
        area = int(values.get("WIDTH", "0")) * int(values.get("HEIGHT", "0"))
        if area > best_area:
            best, best_area = window_id, area
    return best


def _browser_pid() -> int:
    result = _run(["pgrep", "-o", "-f", "firefox.*nest-secure-browser"])
    with contextlib.suppress(ValueError):
        return int(result.stdout.decode().strip())
    return 0


def _redact_url(value: str) -> str:
    value = value.strip()
    if "://" not in value and not value.startswith("about:") and not any(char.isspace() for char in value):
        value = f"https://{value}"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https", "about"}:
        return ""
    if parsed.scheme == "about":
        return value if value in {"about:blank", "about:newtab", "about:home"} else "about:<redacted>"
    host = parsed.hostname or ""
    if not host:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, host + port, parsed.path[:300], "", ""))


def _identity(role: str, name: str, path: tuple[int, ...], generation: int) -> str:
    # A page-tab accessible's name is the page title, so it changes after
    # every successful navigation. Its position is the durable identity while
    # the tab exists; other controls retain name hashing to reject stale
    # locators when content at an accessibility path changes.
    identity_name = "" if role == "page tab" else name
    digest = hashlib.sha256(f"{role}\0{identity_name}".encode()).hexdigest()[:12]
    encoded_path = ".".join(str(index) for index in path)
    return f"ax:{generation}:{encoded_path}:{digest}"


def _safe_name(role: str, name: str) -> str:
    compact = " ".join((name or "").split())[:MAX_NAME]
    if role in {"password text", "password"} or SENSITIVE_RE.search(compact):
        return "<sensitive control; value redacted>"
    return compact


def _state_names(node: Any) -> list[str]:
    result: list[str] = []
    with contextlib.suppress(Exception):
        states = node.get_state_set()
        for label, enum_name in (
            ("focused", "FOCUSED"), ("focusable", "FOCUSABLE"),
            ("selected", "SELECTED"), ("editable", "EDITABLE"),
            ("enabled", "ENABLED"), ("visible", "VISIBLE"),
            ("showing", "SHOWING"), ("checked", "CHECKED"),
        ):
            gi = importlib.import_module("gi")
            gi.require_version("Atspi", "2.0")
            Atspi = importlib.import_module("gi.repository.Atspi")
            if states.contains(getattr(Atspi.StateType, enum_name)):
                result.append(label)
    return result


def _extent(node: Any) -> dict[str, int] | None:
    with contextlib.suppress(Exception):
        gi = importlib.import_module("gi")
        gi.require_version("Atspi", "2.0")
        Atspi = importlib.import_module("gi.repository.Atspi")
        component = node.get_component_iface()
        if component:
            rect = component.get_extents(Atspi.CoordType.SCREEN)
            if rect.width > 0 and rect.height > 0:
                return {"x": int(rect.x), "y": int(rect.y), "width": int(rect.width), "height": int(rect.height)}
    return None


def _desktop() -> Any:
    _load_session_environment()
    gi = importlib.import_module("gi")
    gi.require_version("Atspi", "2.0")
    Atspi = importlib.import_module("gi.repository.Atspi")
    return Atspi.get_desktop(0)


def _firefox_root() -> Any:
    desktop = _desktop()
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if "firefox" in (app.get_name() or "").lower():
            return app
    raise RuntimeError("Firefox is not registered on the AT-SPI session bus")


def _walk(root: Any) -> Iterable[tuple[Any, tuple[int, ...]]]:
    stack: list[tuple[Any, tuple[int, ...]]] = [(root, ())]
    visited = 0
    while stack and visited < MAX_NODES * 8:
        node, path = stack.pop()
        visited += 1
        yield node, path
        with contextlib.suppress(Exception):
            count = min(node.get_child_count(), 1000)
            for index in range(count - 1, -1, -1):
                child = node.get_child_at_index(index)
                if child is not None:
                    stack.append((child, path + (index,)))


def _snapshot() -> dict[str, Any]:
    generation = _browser_pid()
    nodes: list[dict[str, Any]] = []
    tabs: list[dict[str, Any]] = []
    address = ""
    root = _firefox_root()
    for node, path in _walk(root):
        with contextlib.suppress(Exception):
            role = node.get_role_name() or "unknown"
            raw_name = node.get_name() or ""
            states = _state_names(node)
            extent = _extent(node)
            if role == "page tab":
                tabs.append({
                    "name": _safe_name(role, raw_name),
                    "selected": "selected" in states,
                    "locator": _identity(role, raw_name, path, generation),
                })
            if role in {"entry", "text"} and any(term in raw_name.lower() for term in ("address", "search with", "enter address")):
                with contextlib.suppress(Exception):
                    text_iface = node.get_text_iface()
                    candidate = text_iface.get_text(0, -1) if text_iface else ""
                    if candidate:
                        address = _redact_url(candidate)
            include = (
                bool(raw_name)
                and "showing" in states
                and (role in INTERACTIVE_ROLES or role in {"heading", "document web", "alert", "notification"})
            )
            if include and len(nodes) < MAX_NODES:
                entry: dict[str, Any] = {
                    "role": role,
                    "name": _safe_name(role, raw_name),
                    "states": states,
                    "locator": _identity(role, raw_name, path, generation),
                }
                if extent:
                    entry["rect"] = extent
                nodes.append(entry)
    window_id = _firefox_window_id()
    title = _run(["xdotool", "getwindowname", window_id]).stdout.decode(errors="replace").strip()[:300]
    return {
        "protocol": "firefox-ui-v1",
        "browser_generation": generation,
        "window_id": window_id,
        "title": title,
        "url": address,
        "tab_count": len(tabs),
        "tabs": tabs,
        "nodes": nodes,
        "truncated": len(nodes) >= MAX_NODES,
        "observation_boundary": "AT-SPI accessibility tree; no DOM, page script, browser debugging protocol, cookies, storage, or profile inspection",
    }


def _resolve_locator(locator: str) -> tuple[Any, dict[str, int] | None]:
    match = re.fullmatch(r"ax:(\d+):([0-9.]*):([0-9a-f]{12})", locator)
    if not match:
        raise ValueError("invalid or unsupported accessibility locator")
    generation = int(match.group(1))
    if generation != _browser_pid():
        raise ValueError("stale accessibility locator: Firefox generation changed")
    path = tuple(int(item) for item in match.group(2).split(".") if item != "")
    node = _firefox_root()
    for index in path:
        node = node.get_child_at_index(index)
        if node is None:
            raise ValueError("stale accessibility locator: node no longer exists")
    role = node.get_role_name() or "unknown"
    name = node.get_name() or ""
    expected = _identity(role, name, path, generation).rsplit(":", 1)[1]
    if expected != match.group(3):
        raise ValueError("stale accessibility locator: control identity changed")
    return node, _extent(node)


def _focus_browser() -> str:
    window_id = _firefox_window_id()
    activated = _run(["xdotool", "windowactivate", "--sync", window_id])
    if activated.returncode != 0:
        # The deliberately minimal xmonad config used by browser.eyrie does not
        # advertise EWMH _NET_ACTIVE_WINDOW. XSetInputFocus still targets this
        # dedicated remote desktop without involving Joy's local desktop.
        _xdotool("windowfocus", "--sync", window_id)
    return window_id


def _readback() -> dict[str, Any]:
    time.sleep(float(os.environ.get("FIREFOX_UI_READBACK_DELAY", "0.45")))
    snapshot = _snapshot()
    selected = _selected_tab(snapshot) or {}
    return {
        "browser_generation": snapshot["browser_generation"],
        "title": snapshot["title"],
        "url": snapshot["url"],
        "tab_count": snapshot["tab_count"],
        "selected_tab": selected.get("name", ""),
        "selected_locator": selected.get("locator", ""),
    }


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": 1, "workflows": {}, "action_keys": {}}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "workflows": {}, "action_keys": {}}
    if not isinstance(state, dict):
        return {"version": 1, "workflows": {}, "action_keys": {}}
    state.setdefault("workflows", {})
    state.setdefault("action_keys", {})
    return state


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(_json(state) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, STATE_PATH)


@contextlib.contextmanager
def _locked_state() -> Iterator[dict[str, Any]]:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock:
        os.chmod(LOCK_PATH, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _load_state()
        try:
            yield state
        finally:
            # A UI action can already have reached Firefox when accessibility
            # readback fails. Persist action keys and ownership updates even on
            # that error path so a retry cannot blindly deliver the action a
            # second time.
            _save_state(state)


def _selected_tab(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    return next((tab for tab in snapshot["tabs"] if tab.get("selected")), None)


def _matching_tabs(snapshot: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer the exact same accessibility tab before title recovery."""
    exact = [tab for tab in snapshot["tabs"] if tab.get("locator") == record.get("locator")]
    if exact:
        return exact
    return [tab for tab in snapshot["tabs"] if tab.get("name") == record.get("tab_name")]


def _reconcile_state(state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    current_generation = snapshot["browser_generation"]
    tabs = snapshot["tabs"]
    report = {"expired": [], "closed_expired": [], "preserved_uncertain": []}
    for workflow_id, record in list(state["workflows"].items()):
        if float(record.get("lease_expires_at", 0)) <= now:
            report["expired"].append(workflow_id)
            if record.get("created_by_agent"):
                matches = _matching_tabs(snapshot, record)
                if len(matches) == 1:
                    _, rect = _resolve_locator(matches[0]["locator"])
                    if rect:
                        _focus_browser()
                        _xdotool("mousemove", "--sync", str(rect["x"] + rect["width"] // 2), str(rect["y"] + rect["height"] // 2), "click", "1")
                        _xdotool("key", "--clearmodifiers", "ctrl+w")
                        report["closed_expired"].append(workflow_id)
                if workflow_id not in report["closed_expired"]:
                    report["preserved_uncertain"].append(workflow_id)
                    record["uncertain"] = True
                    continue
            del state["workflows"][workflow_id]
            continue
        matches = _matching_tabs(snapshot, record)
        if record.get("browser_generation") != current_generation:
            if len(matches) == 1:
                record["browser_generation"] = current_generation
                record["locator"] = matches[0]["locator"]
            else:
                record["uncertain"] = True
                report["preserved_uncertain"].append(workflow_id)
    cutoff = now - 7 * 86400
    state["action_keys"] = {
        key: value for key, value in state["action_keys"].items()
        if float(value.get("created_at", 0)) >= cutoff
    }
    return report


def _ensure_workflow(state: dict[str, Any], workflow_id: str, lease_seconds: int, *, allow_create: bool) -> tuple[dict[str, Any], bool]:
    snapshot = _snapshot()
    _reconcile_state(state, snapshot)
    existing = state["workflows"].get(workflow_id)
    if existing and existing.get("uncertain"):
        raise RuntimeError("canonical tab ownership is uncertain; preserving tabs and refusing to replace the workflow binding")
    if existing:
        matching = _matching_tabs(snapshot, existing)
        if len(matching) == 1:
            existing["locator"] = matching[0]["locator"]
            existing["lease_expires_at"] = time.time() + lease_seconds
            return existing, False
        existing["uncertain"] = True
        raise RuntimeError("canonical tab identity is missing or ambiguous; preserving tabs and refusing to replace the workflow binding")
    selected = _selected_tab(snapshot)
    if selected and selected["name"] in {"New Tab", "New Private Tab", "about:blank", "Firefox"}:
        created = False
    elif allow_create:
        if snapshot["tab_count"] >= DEFAULT_HARD_TAB_CAP:
            raise RuntimeError(f"local tab hard cap reached ({DEFAULT_HARD_TAB_CAP}); refusing to create a tab or close unowned tabs")
        _focus_browser()
        _xdotool("key", "--clearmodifiers", "ctrl+t")
        snapshot = _snapshot()
        selected = _selected_tab(snapshot)
        created = True
    else:
        raise RuntimeError("no safely claimable blank handoff tab; call tab_lifecycle acquire explicitly")
    if not selected:
        raise RuntimeError("Firefox accessibility tree did not expose a selected tab")
    record = {
        "workflow_id": workflow_id,
        "browser_generation": snapshot["browser_generation"],
        "tab_name": selected["name"],
        "locator": selected["locator"],
        "created_by_agent": created,
        "created_at": time.time(),
        "lease_expires_at": time.time() + lease_seconds,
        "uncertain": False,
    }
    state["workflows"][workflow_id] = record
    return record, created


def _select_workflow_tab(record: dict[str, Any]) -> None:
    snapshot = _snapshot()
    matches = _matching_tabs(snapshot, record)
    if len(matches) != 1:
        raise RuntimeError("canonical tab identity is ambiguous; preserving tabs and refusing input")
    if matches[0].get("selected"):
        return
    node, rect = _resolve_locator(matches[0]["locator"])
    if not rect:
        raise RuntimeError("canonical tab has no actionable screen bounds")
    _focus_browser()
    _xdotool("mousemove", "--sync", str(rect["x"] + rect["width"] // 2), str(rect["y"] + rect["height"] // 2), "click", "1")


def command_status(_: dict[str, Any]) -> dict[str, Any]:
    snapshot = _snapshot()
    with _locked_state() as state:
        reconciliation = _reconcile_state(state, snapshot)
        if reconciliation["closed_expired"]:
            snapshot = _snapshot()
        workflows = [
            {
                "workflow_id": key,
                "lease_expires_at": value.get("lease_expires_at"),
                "created_by_agent": bool(value.get("created_by_agent")),
                "uncertain": bool(value.get("uncertain")),
            }
            for key, value in state["workflows"].items()
        ]
    return {
        "operation": "status", "status": "ok", "protocol": "firefox-ui-v1",
        "browser": {key: snapshot[key] for key in ("browser_generation", "title", "url", "tab_count")},
        "workflows": workflows, "reconciliation": reconciliation,
        "instrumentation": {"webdriver": False, "marionette": False, "bidi": False, "cdp": False, "dom": False},
    }


def command_snapshot(_: dict[str, Any]) -> dict[str, Any]:
    return {"operation": "snapshot", "status": "ok", **_snapshot()}


def command_navigate(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https", "about"}:
        raise ValueError("navigation URL must use http, https, or about")
    workflow_id = str(payload.get("workflow_id") or "default")[:160]
    lease = max(60, min(int(payload.get("lease_seconds") or DEFAULT_LEASE_SECONDS), 86400))
    with _locked_state() as state:
        record, created = _ensure_workflow(state, workflow_id, lease, allow_create=False)
        _select_workflow_tab(record)
        _xdotool("key", "--clearmodifiers", "ctrl+l")
        _xdotool("type", "--clearmodifiers", "--delay", "1", "--", url, timeout=30)
        _xdotool("key", "--clearmodifiers", "Return")
        readback = _readback()
        record["tab_name"] = readback["selected_tab"]
        record["locator"] = readback.get("selected_locator") or record["locator"]
        record["lease_expires_at"] = time.time() + lease
    return {"operation": "navigate", "status": "delivered", "created_tab": created, "workflow_id": workflow_id, "readback": readback}


def command_click(payload: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(payload.get("workflow_id") or "default")[:160]
    locator = str(payload.get("locator") or "")
    coordinate = payload.get("coordinate")
    action_key = str(payload.get("action_key") or "")[:200]
    with _locked_state() as state:
        snapshot = _snapshot()
        _reconcile_state(state, snapshot)
        record = state["workflows"].get(workflow_id)
        if not record or record.get("uncertain"):
            raise RuntimeError("workflow has no unambiguous canonical handoff tab")
        if action_key and action_key in state["action_keys"]:
            delivered = state["action_keys"][action_key]
            if delivered.get("workflow_id") != workflow_id:
                raise ValueError("action_key is already bound to another workflow")
            _select_workflow_tab(record)
            return {"operation": "click", "status": "already_delivered", "action_key": action_key, "readback": _readback()}
        _select_workflow_tab(record)
        if locator:
            _, rect = _resolve_locator(locator)
            if not rect:
                raise ValueError("accessibility control has no screen bounds")
            x, y = rect["x"] + rect["width"] // 2, rect["y"] + rect["height"] // 2
        elif isinstance(coordinate, list) and len(coordinate) == 2:
            x, y = int(coordinate[0]), int(coordinate[1])
        else:
            raise ValueError("click requires an accessibility locator or [x,y] coordinate")
        _xdotool("mousemove", "--sync", str(x), str(y), "click", "1")
        if action_key:
            state["action_keys"][action_key] = {"created_at": time.time(), "workflow_id": workflow_id}
        readback = _readback()
        record["tab_name"] = readback["selected_tab"] or record["tab_name"]
        record["locator"] = readback.get("selected_locator") or record["locator"]
    return {"operation": "click", "status": "delivered", "action_key": action_key or None, "coordinate": [x, y], "readback": readback}


def command_type(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    if not text or len(text) > 4096:
        raise ValueError("text must contain 1..4096 characters")
    workflow_id = str(payload.get("workflow_id") or "default")[:160]
    locator = str(payload.get("locator") or "")
    with _locked_state() as state:
        snapshot = _snapshot()
        _reconcile_state(state, snapshot)
        record = state["workflows"].get(workflow_id)
        if not record or record.get("uncertain"):
            raise RuntimeError("workflow has no unambiguous canonical handoff tab")
        _select_workflow_tab(record)
        if locator:
            _, rect = _resolve_locator(locator)
            if not rect:
                raise ValueError("accessibility control has no screen bounds")
            _xdotool("mousemove", "--sync", str(rect["x"] + rect["width"] // 2), str(rect["y"] + rect["height"] // 2), "click", "1")
        _xdotool("type", "--clearmodifiers", "--delay", "1", "--", text, timeout=45)
        readback = _readback()
        record["tab_name"] = readback["selected_tab"] or record["tab_name"]
        record["locator"] = readback.get("selected_locator") or record["locator"]
    return {"operation": "type", "status": "delivered", "typed_chars": len(text), "text_redacted": True, "readback": readback}


def command_screenshot(_: dict[str, Any]) -> dict[str, Any]:
    window_id = _firefox_window_id()
    geometry_text = _run(["xdotool", "getwindowgeometry", "--shell", window_id]).stdout.decode()
    geometry = dict(line.split("=", 1) for line in geometry_text.splitlines() if "=" in line)
    width, height = int(geometry["WIDTH"]), int(geometry["HEIGHT"])
    result = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "x11grab",
        "-video_size", f"{width}x{height}", "-i", f"{DISPLAY}+{geometry.get('X', '0')},{geometry.get('Y', '0')}",
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
    ], timeout=30)
    if result.returncode != 0 or not result.stdout.startswith(b"\x89PNG"):
        raise RuntimeError(f"X11 screenshot failed: {result.stderr.decode(errors='replace')[:500]}")
    return {
        "operation": "screenshot", "status": "ok", "mime_type": "image/png",
        "width": width, "height": height, "png_base64": base64.b64encode(result.stdout).decode(),
        "safety_note": "Visible Firefox desktop capture; callers must not expose owner-sensitive pages outside the directed workflow.",
    }


def command_tabs(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "status")
    workflow_id = str(payload.get("workflow_id") or "default")[:160]
    lease = max(60, min(int(payload.get("lease_seconds") or DEFAULT_LEASE_SECONDS), 86400))
    with _locked_state() as state:
        snapshot = _snapshot()
        reconciliation = _reconcile_state(state, snapshot)
        if action == "acquire":
            record, created = _ensure_workflow(state, workflow_id, lease, allow_create=True)
            return {"operation": "tab_lifecycle", "status": "ok", "action": action, "created_tab": created, "workflow_id": workflow_id, "lease_expires_at": record["lease_expires_at"], "tab_count": _snapshot()["tab_count"]}
        if action == "keep_open":
            record = state["workflows"].get(workflow_id)
            if not record:
                raise ValueError("unknown workflow")
            record["lease_expires_at"] = time.time() + lease
            return {"operation": "tab_lifecycle", "status": "ok", "action": action, "workflow_id": workflow_id, "lease_expires_at": record["lease_expires_at"]}
        if action == "release":
            record = state["workflows"].get(workflow_id)
            if not record:
                return {"operation": "tab_lifecycle", "status": "already_released", "action": action, "workflow_id": workflow_id}
            if not record.get("created_by_agent"):
                del state["workflows"][workflow_id]
                return {"operation": "tab_lifecycle", "status": "released_preserved_tab", "action": action, "workflow_id": workflow_id}
            current = _snapshot()
            matches = _matching_tabs(current, record)
            if len(matches) != 1:
                record["uncertain"] = True
                return {"operation": "tab_lifecycle", "status": "preserved_uncertain", "action": action, "workflow_id": workflow_id}
            node, rect = _resolve_locator(matches[0]["locator"])
            if not rect:
                record["uncertain"] = True
                return {"operation": "tab_lifecycle", "status": "preserved_uncertain", "action": action, "workflow_id": workflow_id}
            _focus_browser()
            _xdotool("mousemove", "--sync", str(rect["x"] + rect["width"] // 2), str(rect["y"] + rect["height"] // 2), "click", "1")
            _xdotool("key", "--clearmodifiers", "ctrl+w")
            del state["workflows"][workflow_id]
            return {"operation": "tab_lifecycle", "status": "released_closed_owned_tab", "action": action, "workflow_id": workflow_id, "readback": _readback()}
        if action != "status":
            raise ValueError("tab lifecycle action must be status, acquire, keep_open, or release")
        return {"operation": "tab_lifecycle", "status": "ok", "action": action, "tab_count": snapshot["tab_count"], "workflows": list(state["workflows"]), "reconciliation": reconciliation, "hard_cap": DEFAULT_HARD_TAB_CAP}


COMMANDS = {
    "status": command_status,
    "snapshot": command_snapshot,
    "navigate": command_navigate,
    "click": command_click,
    "type": command_type,
    "screenshot": command_screenshot,
    "tabs": command_tabs,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        result = COMMANDS[args.command](payload)
    except Exception as exc:
        result = {"status": "error", "error": type(exc).__name__, "message": str(exc)[:1000], "protocol": "firefox-ui-v1"}
    print(_json(result))
    return 0 if result.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
