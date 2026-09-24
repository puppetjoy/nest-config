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
MAX_PAGE_TEXT = 2048
DEFAULT_STABLE_WAIT_SECONDS = float(os.environ.get("FIREFOX_UI_STABLE_WAIT_SECONDS", "6"))
SENSITIVE_RE = re.compile(
    r"password|passcode|one[- ]?time|security code|cvv|cvc|card number|account number|routing number|secret|token|private key|recovery code",
    re.IGNORECASE,
)
OWNER_SENSITIVE_RE = re.compile(
    r"@|\b(?:name|email|address|street|road|avenue|lane|drive|boulevard|postal|zip|phone|card|visa|mastercard|amex)\b|\b\d{4}[ -]?\d{4}\b",
    re.IGNORECASE,
)
INTERACTIVE_ROLES = {
    "push button", "button", "check box", "combo box", "entry", "link",
    "menu item", "page tab", "radio button", "slider", "spin button",
    "text", "toggle button",
}
PROSE_ROLES = {"heading", "document web", "alert", "notification", "static", "static text", "paragraph"}
PRIVATE_VALUE_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b(?:\d[ -]*?){13,19}\b")
TERMINAL_SUCCESS_RE = re.compile(
    r"\b(?:order (?:is )?confirmed|purchase (?:is )?complete|payment (?:was )?successful|thank you for your (?:order|purchase)|confirmation status[: ]+confirmed)\b",
    re.IGNORECASE,
)
TERMINAL_ERROR_RE = re.compile(
    r"\b(?:payment (?:was )?(?:failed|declined)|order (?:could not|was not) (?:be )?(?:placed|processed)|unable to process|transaction failed|checkout error)\b",
    re.IGNORECASE,
)
IN_FLIGHT_RE = re.compile(
    r"\b(?:processing (?:payment|order)|placing (?:your )?order|please wait|loading|submitting)\b",
    re.IGNORECASE,
)
COMMERCE_CONTEXT_RE = re.compile(r"\b(?:cart|checkout|order|payment|purchase|receipt|confirmation)\b", re.IGNORECASE)
MONEY_RE = re.compile(r"(?<!\w)([$€£]\s?\d[\d,]*(?:\.\d{2})?)(?!\w)")


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


def _control_id(role: str, path: tuple[int, ...], generation: int) -> str:
    """Opaque path identity that does not depend on an accessible name."""
    digest = hashlib.sha256(role.encode()).hexdigest()[:12]
    encoded_path = ".".join(str(index) for index in path)
    return f"ui:{generation}:{encoded_path}:{digest}"


def _safe_name(role: str, name: str) -> str:
    compact = " ".join((name or "").split())[:MAX_NAME]
    if role in {"password text", "password"} or SENSITIVE_RE.search(compact):
        return "<sensitive control; value redacted>"
    return compact


def _text_content(node: Any) -> str:
    """Read AT-SPI text through the interface's static GI methods."""
    with contextlib.suppress(Exception):
        Atspi = importlib.import_module("gi.repository.Atspi")
        count = int(Atspi.Text.get_character_count(node))
        if count > 0:
            return str(Atspi.Text.get_text(node, 0, min(count, MAX_PAGE_TEXT)) or "")
    return ""


def _safe_visible_commerce_text(value: str) -> str:
    """Canonicalize only checkout-safe visible text and drop all other prose."""
    compact = " ".join((value or "").split())
    if not compact:
        return ""
    if TERMINAL_ERROR_RE.search(compact):
        return "Payment failed"
    if TERMINAL_SUCCESS_RE.search(compact):
        return "Order confirmed"
    if IN_FLIGHT_RE.search(compact):
        return "Processing payment"
    quantity = re.search(r"\b(?:quantity|qty)\s*[:x-]?\s*(\d{1,3})\b", compact, re.IGNORECASE)
    if quantity:
        return f"Quantity {quantity.group(1)}"
    money = MONEY_RE.search(compact)
    if money and not compact[money.end():].strip():
        label = compact[:money.start()].strip(" :-").lower()
        canonical_labels = {
            "subtotal": "Subtotal", "shipping": "Shipping", "tax": "Tax",
            "total": "Total", "order total": "Total", "grand total": "Total",
        }
        if label in canonical_labels:
            return f"{canonical_labels[label]} {re.sub(r'\s+', '', money.group(1))}"
    if re.fullmatch(r"shipping\s*[: -]?\s*free", compact, re.IGNORECASE):
        return "Shipping free"
    return ""


def _safe_observed_name(role: str, accessible_name: str, text_content: str) -> str:
    if role in {"password", "password text"}:
        return "<sensitive control; value redacted>"
    text_bearing = role in PROSE_ROLES | {"text", "entry", "spin button"} or role not in INTERACTIVE_ROLES
    source = (text_content or accessible_name) if text_bearing else accessible_name
    value = " ".join(source.split())
    if SENSITIVE_RE.search(accessible_name) or PRIVATE_VALUE_RE.search(value):
        return "<sensitive control; value redacted>"
    return value[:MAX_PAGE_TEXT]


def _state_names(node: Any) -> list[str]:
    result: list[str] = []
    with contextlib.suppress(Exception):
        states = node.get_state_set()
        for label, enum_name in (
            ("focused", "FOCUSED"), ("focusable", "FOCUSABLE"),
            ("selected", "SELECTED"), ("editable", "EDITABLE"),
            ("enabled", "ENABLED"), ("visible", "VISIBLE"),
            ("showing", "SHOWING"), ("checked", "CHECKED"),
            ("pressed", "PRESSED"), ("active", "ACTIVE"),
            ("expanded", "EXPANDED"), ("indeterminate", "INDETERMINATE"),
        ):
            with contextlib.suppress(Exception):
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


def _node_record(node: Any, path: tuple[int, ...], generation: int, observed_name: str | None = None) -> dict[str, Any]:
    role = node.get_role_name() or "unknown"
    raw_name = node.get_name() or ""
    display_name = raw_name if observed_name is None else observed_name
    description = ""
    with contextlib.suppress(Exception):
        description = node.get_description() or ""
    states = _state_names(node)
    extent = _extent(node)
    safe_name = _safe_name(role, display_name) if role in INTERACTIVE_ROLES or observed_name is None else display_name[:MAX_PAGE_TEXT]
    record: dict[str, Any] = {
        "role": role,
        "name": safe_name or "<unlabelled>",
        "accessible_name_present": bool(safe_name),
        "unlabelled": not bool(safe_name),
        "states": states,
        "control_id": _control_id(role, path, generation),
        "locator": _identity(role, raw_name, path, generation),
    }
    safe_description = "" if role in PROSE_ROLES else _safe_name(role, description)
    if safe_description:
        record["description"] = safe_description
    if role in {"entry", "spin button", "text"}:
        value = _safe_observed_name(role, raw_name, _text_content(node))
        if value and value != raw_name:
            record["value"] = value
    if extent:
        record["rect"] = extent
    return record


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
                candidate = _text_content(node)
                if candidate:
                    address = _redact_url(candidate)
            text_content = _text_content(node) if "showing" in states or "visible" in states else ""
            observed_name = _safe_observed_name(role, raw_name, text_content)
            # Container text interfaces often repeat their entire descendant
            # subtree. Include unfamiliar text-bearing *leaves*, not parent
            # containers that would exhaust the node budget before controls.
            leaf_text = False
            if text_content and role not in INTERACTIVE_ROLES | PROSE_ROLES:
                with contextlib.suppress(Exception):
                    leaf_text = node.get_child_count() == 0
            prose_name = observed_name if role in PROSE_ROLES or leaf_text else ""
            include = "showing" in states and (
                role in INTERACTIVE_ROLES
                or bool(prose_name)
            )
            include = include or bool(prose_name and "visible" in states)
            if include and len(nodes) < MAX_NODES:
                nodes.append(_node_record(node, path, generation, observed_name))
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
        "observation_boundary": "AT-SPI accessibility tree and visible text; no DOM, page script, browser debugging protocol, cookies, storage, or profile inspection",
    }


def _snapshot_text(snapshot: dict[str, Any]) -> str:
    names = [str(node.get("name") or "") for node in snapshot.get("nodes", [])]
    return "\n".join([str(snapshot.get("title") or ""), *names])


def _transition_state(snapshot: dict[str, Any]) -> str:
    page_status_text = "\n".join(
        str(node.get("name") or "")
        for node in snapshot.get("nodes", [])
        if str(node.get("role") or "") in {"heading", "alert", "notification", "static", "static text", "paragraph"}
    )
    terminal_context = "\n".join((str(snapshot.get("title") or ""), str(snapshot.get("url") or "")))
    if COMMERCE_CONTEXT_RE.search(terminal_context) and TERMINAL_ERROR_RE.search(page_status_text):
        return "terminal_error"
    if COMMERCE_CONTEXT_RE.search(terminal_context) and TERMINAL_SUCCESS_RE.search(page_status_text):
        return "terminal_success"
    # Browser chrome and background-tab names are part of the AT-SPI tree. A
    # stale tab named "Problem loading page" must not classify the selected
    # checkout as in flight; only safe, visible page prose can carry progress.
    if IN_FLIGHT_RE.search(page_status_text):
        return "in_flight"
    nodes = list(snapshot.get("nodes", []))
    if not nodes or (
        len(nodes) == 1
        and (
            str(nodes[0].get("role") or "") == "document web"
            or str(nodes[0].get("name") or "").strip().lower() in {"document", "<unlabelled>"}
        )
    ):
        return "in_flight"
    return "stable"


def _snapshot_signature(snapshot: dict[str, Any]) -> str:
    bounded_nodes = [
        (
            node.get("control_id"), node.get("role"), node.get("name"),
            tuple(node.get("states") or ()), node.get("rect"),
        )
        for node in snapshot.get("nodes", [])[:MAX_NODES]
    ]
    return hashlib.sha256(_json({
        "title": snapshot.get("title"),
        "url": snapshot.get("url"),
        "selected": (_selected_tab(snapshot) or {}).get("locator"),
        "nodes": bounded_nodes,
    }).encode()).hexdigest()


def _wait_for_stable(*, max_wait_seconds: float = DEFAULT_STABLE_WAIT_SECONDS, stable_polls: int = 2) -> dict[str, Any]:
    bounded_wait = max(0.0, min(float(max_wait_seconds), 15.0))
    deadline = time.monotonic() + bounded_wait
    previous_signature = ""
    matching_polls = 0
    polls = 0
    snapshot: dict[str, Any] = {}
    while True:
        snapshot = _snapshot()
        polls += 1
        signature = _snapshot_signature(snapshot)
        matching_polls = matching_polls + 1 if signature == previous_signature else 1
        previous_signature = signature
        state = _transition_state(snapshot)
        if state in {"terminal_success", "terminal_error"} and matching_polls >= stable_polls:
            settled = True
            break
        if state == "stable" and matching_polls >= stable_polls:
            settled = True
            break
        if time.monotonic() >= deadline:
            settled = False
            break
        time.sleep(0.25)
    return {
        "state": _transition_state(snapshot),
        "settled": settled,
        "terminal": _transition_state(snapshot) in {"terminal_success", "terminal_error"},
        "polls": polls,
        "max_wait_seconds": bounded_wait,
        "snapshot": snapshot,
    }


def _commerce_readback(snapshot: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    nickname = " ".join(str(payload.get("safe_item_nickname") or "").split())[:120]
    if not nickname:
        raise ValueError("safe_item_nickname is required")
    host = urlsplit(str(snapshot.get("url") or "")).hostname or ""
    visible_names = []
    for node in snapshot.get("nodes", []):
        name = " ".join(str(node.get("name") or "").split())
        value = " ".join(str(node.get("value") or "").split())
        if name and name != "<unlabelled>" and not name.startswith("<sensitive"):
            visible_names.append(name)
        if value and not value.startswith("<sensitive") and value != name:
            visible_names.append(value)

    def amount_for(label: str) -> str | None:
        label_re = re.compile(rf"\b{re.escape(label)}\b", re.IGNORECASE)
        values: list[str] = []
        for index, text in enumerate(visible_names):
            if not label_re.search(text):
                continue
            following = visible_names[index + 1] if index + 1 < len(visible_names) else ""
            match = MONEY_RE.search(text)
            currency_suffix = text[match.end():].strip() if match else ""
            amount_ends_line = not currency_suffix or bool(re.fullmatch(r"(?:USD|CAD|AUD|EUR|GBP)", currency_suffix, re.IGNORECASE))
            if label == "total":
                accepted_labels = {"total", "order total", "grand total"}
                if match and text[:match.start()].strip(" :-").lower() in accepted_labels and amount_ends_line:
                    values.append(re.sub(r"\s+", "", match.group(1)))
                elif text.strip(" :-").lower() in accepted_labels:
                    split_match = MONEY_RE.fullmatch(following)
                    if split_match:
                        values.append(re.sub(r"\s+", "", split_match.group(1)))
                continue
            # A shipping promotion or threshold banner is not a charge.
            # Accept only a standalone checkout line label, not arbitrary prose
            # containing the word (e.g. "free shipping on orders over $100").
            accepted_labels = {"shipping", "shipping cost", "shipping charge", "delivery", "delivery fee"} if label == "shipping" else {label}
            if match and text[:match.start()].strip(" :-").lower() in accepted_labels and amount_ends_line:
                values.append(re.sub(r"\s+", "", match.group(1)))
                continue
            if text.strip(" :-").lower() not in accepted_labels:
                continue
            match = MONEY_RE.fullmatch(following)
            if match:
                values.append(re.sub(r"\s+", "", match.group(1)))
                continue
            if label == "shipping" and re.fullmatch(r"free", following, re.IGNORECASE):
                values.append("free")
                continue
            if label == "shipping" and re.search(r"\bfree\b", text, re.IGNORECASE):
                values.append("free")
        return values[-1] if values else None

    variants: list[str] = []
    for node in snapshot.get("nodes", []):
        states = set(node.get("states") or [])
        if not states.intersection({"selected", "checked", "pressed", "active"}):
            continue
        name = " ".join(str(node.get("name") or "").split())
        match = re.match(r"(?:color|colour|size)\s*[:\-]\s*(.{1,80})$", name, re.IGNORECASE)
        if match and not SENSITIVE_RE.search(match.group(1)) and not OWNER_SENSITIVE_RE.search(match.group(1)):
            value = match.group(1).strip()
            if value not in variants:
                variants.append(value)

    # Prefer labelled control values: a cart often has a separate Quantity
    # spin button on every row, not prose containing "Quantity 1".
    control_quantities = [
        int(str(node.get("value"))) for node in snapshot.get("nodes", [])
        if str(node.get("role") or "") in {"spin button", "entry"}
        and re.fullmatch(r"(?:quantity|qty)", str(node.get("name") or ""), re.IGNORECASE)
        and re.fullmatch(r"\d{1,3}", str(node.get("value") or ""))
    ]
    if not control_quantities:
        # Some sites name quantity spin buttons with the number itself. Only
        # treat them as quantities when bracketed by decrement/increment
        # controls in the same accessibility reading order.
        nodes = list(snapshot.get("nodes", []))
        control_quantities = [
            int(value) for index, node in enumerate(nodes)
            if node.get("role") == "spin button"
            for value in [str(node.get("value") or node.get("name") or "")]
            if re.fullmatch(r"\d{1,3}", value)
            and index > 0 and index + 1 < len(nodes)
            and re.fullmatch(r"(?:decrease|decrement|minus|remove one)", str(nodes[index - 1].get("name") or ""), re.IGNORECASE)
            and re.fullmatch(r"(?:increase|increment|plus|add one)", str(nodes[index + 1].get("name") or ""), re.IGNORECASE)
        ]
    quantity: int | None = sum(control_quantities) if control_quantities else None
    if quantity is None:
        for text in visible_names:
            match = re.search(r"\b(?:quantity|qty)\s*[:x-]?\s*(\d{1,3})\b", text, re.IGNORECASE)
            if match:
                quantity = int(match.group(1))
                break

    transition = _transition_state(snapshot)
    confirmation = {
        "terminal_success": "confirmed",
        "terminal_error": "failed",
        "in_flight": "in_flight",
        "stable": "not_confirmed",
    }[transition]
    return {
        "operation": "checkout_readback",
        "status": "ok",
        "protocol": "firefox-ui-v1",
        "source": "visible AT-SPI accessibility readback",
        "retailer": host,
        "safe_item_nickname": nickname,
        "variant": variants,
        "quantity": quantity,
        "subtotal": amount_for("subtotal"),
        "shipping": amount_for("shipping"),
        "tax": amount_for("tax"),
        "total": amount_for("total"),
        "confirmation_status": confirmation,
        "transition_state": transition,
        "truncated": bool(snapshot.get("truncated")),
        "redaction": {
            "owner_name": True, "email": True, "address": True,
            "payment_details": True, "raw_order_id": True, "raw_page_text": True,
        },
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


def _readback(max_wait_seconds: float = DEFAULT_STABLE_WAIT_SECONDS) -> dict[str, Any]:
    time.sleep(float(os.environ.get("FIREFOX_UI_READBACK_DELAY", "0.45")))
    transition = _wait_for_stable(max_wait_seconds=max_wait_seconds)
    snapshot = transition.pop("snapshot")
    selected = _selected_tab(snapshot) or {}
    terminal_state = transition["state"]
    safe_title = snapshot["title"]
    safe_url = snapshot["url"]
    safe_selected_tab = selected.get("name", "")
    if terminal_state in {"terminal_success", "terminal_error"}:
        safe_title = "Purchase confirmation" if terminal_state == "terminal_success" else "Purchase error"
        parsed_url = urlsplit(str(snapshot.get("url") or ""))
        safe_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, "", "", "")) if parsed_url.hostname else ""
        safe_selected_tab = safe_title
    return {
        "browser_generation": snapshot["browser_generation"],
        "title": safe_title,
        "url": safe_url,
        "tab_count": snapshot["tab_count"],
        "selected_tab": safe_selected_tab,
        "selected_locator": selected.get("locator", ""),
        "transition": transition,
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
    """Do not treat a reused tab-strip index as durable tab identity."""
    exact = [tab for tab in snapshot["tabs"] if tab.get("locator") == record.get("locator") and tab.get("name") == record.get("tab_name")]
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
                # An expired locator can point to a newer tab after index
                # reuse. Never close an agent-created tab automatically.
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
        previous_count = snapshot["tab_count"]
        _focus_browser()
        _xdotool("key", "--clearmodifiers", "ctrl+t")
        snapshot = _snapshot()
        selected = _selected_tab(snapshot)
        if snapshot["tab_count"] != previous_count + 1 or not selected or selected["name"] not in {"New Tab", "New Private Tab", "about:blank", "Firefox"}:
            raise RuntimeError("new Firefox tab was not visibly selected after Ctrl+T; refusing to claim or navigate another tab")
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
        readback = _readback(float(payload.get("max_wait_seconds") or DEFAULT_STABLE_WAIT_SECONDS))
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
            delivery_state = delivered.get("delivery_state", "delivered")
            return {
                "operation": "click",
                "status": "already_delivered" if delivery_state == "delivered" else "delivery_uncertain",
                "action_key": action_key,
                "delivery": {
                    "state": "replayed" if delivery_state == "delivered" else "uncertain_replay_blocked",
                    "input_sent": False,
                },
                "readback": _readback(float(payload.get("max_wait_seconds") or DEFAULT_STABLE_WAIT_SECONDS)),
            }
        _select_workflow_tab(record)
        if locator:
            node, rect = _resolve_locator(locator)
            if not rect:
                raise ValueError("accessibility control has no screen bounds")
            # Styled radio labels can leave every hidden input at the same AX
            # coordinates. Prefer the accessible action over a guessed pixel.
            if node is not None and node.get_role_name() in {"radio button", "check box"}:
                action = node.get_action_iface()
                if action and action.get_n_actions():
                    if action_key:
                        state["action_keys"][action_key] = {"created_at": time.time(), "workflow_id": workflow_id, "delivery_state": "delivery_started"}
                        _save_state(state)
                    if not action.do_action(0):
                        raise RuntimeError("accessibility action failed; inspect visible control before coordinate fallback")
                    if action_key:
                        state["action_keys"][action_key]["delivery_state"] = "delivered"
                        _save_state(state)
                    readback = _readback(float(payload.get("max_wait_seconds") or DEFAULT_STABLE_WAIT_SECONDS))
                    record["tab_name"] = readback["selected_tab"] or record["tab_name"]
                    record["locator"] = readback.get("selected_locator") or record["locator"]
                    return {"operation": "click", "status": "delivered", "action_key": action_key or None,
                            "delivery": {"state": "delivered", "input_sent": True, "via": "accessibility_action"}, "readback": readback}
                same_bounds = [item for item in snapshot["nodes"] if item.get("rect") == rect and item.get("role") in {"radio button", "check box"}]
                if len(same_bounds) > 1:
                    raise ValueError("overlapping accessibility bounds; use a visible label coordinate after screenshot review")
            x, y = rect["x"] + rect["width"] // 2, rect["y"] + rect["height"] // 2
        elif isinstance(coordinate, list) and len(coordinate) == 2:
            x, y = int(coordinate[0]), int(coordinate[1])
        else:
            raise ValueError("click requires an accessibility locator or [x,y] coordinate")
        if action_key:
            state["action_keys"][action_key] = {
                "created_at": time.time(), "workflow_id": workflow_id,
                "delivery_state": "delivery_started",
            }
            _save_state(state)
        _xdotool("mousemove", "--sync", str(x), str(y), "click", "1")
        if action_key:
            state["action_keys"][action_key]["delivery_state"] = "delivered"
            _save_state(state)
        readback = _readback(float(payload.get("max_wait_seconds") or DEFAULT_STABLE_WAIT_SECONDS))
        record["tab_name"] = readback["selected_tab"] or record["tab_name"]
        record["locator"] = readback.get("selected_locator") or record["locator"]
    return {
        "operation": "click", "status": "delivered", "action_key": action_key or None,
        "delivery": {"state": "delivered", "input_sent": True},
        "coordinate": [x, y], "readback": readback,
    }


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


def command_wait(payload: dict[str, Any]) -> dict[str, Any]:
    transition = _wait_for_stable(max_wait_seconds=float(payload.get("max_wait_seconds") or DEFAULT_STABLE_WAIT_SECONDS))
    snapshot = transition.pop("snapshot")
    return {
        "operation": "wait", "status": "ok", "protocol": "firefox-ui-v1",
        "transition": transition,
        "browser_generation": snapshot.get("browser_generation"),
        "tab_count": snapshot.get("tab_count"),
    }


def command_checkout_readback(payload: dict[str, Any]) -> dict[str, Any]:
    transition = _wait_for_stable(max_wait_seconds=float(payload.get("max_wait_seconds") or DEFAULT_STABLE_WAIT_SECONDS))
    snapshot = transition.pop("snapshot")
    result = _commerce_readback(snapshot, payload)
    result["progress"] = transition
    return result


def command_scroll(payload: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(payload.get("workflow_id") or "default")[:160]
    direction = str(payload.get("direction") or "down")
    if direction not in {"up", "down"}:
        raise ValueError("scroll direction must be up or down")
    amount = max(1, min(int(payload.get("amount") or 1), 6))
    with _locked_state() as state:
        snapshot = _snapshot()
        _reconcile_state(state, snapshot)
        record = state["workflows"].get(workflow_id)
        if not record or record.get("uncertain"):
            raise RuntimeError("workflow has no unambiguous canonical handoff tab")
        _select_workflow_tab(record)
        key = "Page_Up" if direction == "up" else "Page_Down"
        for _ in range(amount):
            _xdotool("key", "--clearmodifiers", key)
        readback = _readback(3)
        record["tab_name"] = readback["selected_tab"] or record["tab_name"]
        record["locator"] = readback.get("selected_locator") or record["locator"]
    return {
        "operation": "scroll", "status": "delivered", "direction": direction,
        "amount": amount, "readback": readback,
    }


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
    "wait": command_wait,
    "checkout_readback": command_checkout_readback,
    "scroll": command_scroll,
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
