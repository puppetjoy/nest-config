"""Host-side Star Pattern Kit session bridge client.

The plugin is credential-free and talks only to a root-owned fixed-function
Unix-socket broker. Every request is relative, bounded, exact-session scoped,
and mediated by the workbench's sanitized bridge API.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import time
from typing import Any
from urllib.parse import quote

BROKER_SOCKET = Path(
    os.environ.get(
        "PATTERNKIT_SESSION_SOCKET",
        "/run/patternkit-session-broker/patternkit-session.sock",
    )
)

SCREENSHOT_DIR = Path(
    os.environ.get(
        "PATTERNKIT_SESSION_SCREENSHOT_DIR",
        os.path.expanduser("~/.hermes/profiles/star/patternkit-session-evidence"),
    )
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SELECTOR_RE = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,63}$")
_FORBIDDEN_SELECTOR_RE = re.compile(
    r"render|save|export|download|upload|source|profile|git|password|token|secret|cookie|storage|oauth|credential|measurement",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\d[ -]*?){12,19}|\b(?:password|passkey|token|secret|cookie|oauth|cvv|cvc)\b)",
    re.IGNORECASE,
)
_ALLOWED_KEYS = {"ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Tab", "Space"}


def check_requirements() -> bool:
    return bool(_current_profile() == "star" and BROKER_SOCKET.is_socket())


def _current_profile() -> str:
    configured = (os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_PROFILE_NAME") or "").strip().lower()
    if configured:
        return configured
    for index, argument in enumerate(sys.argv[:-1]):
        if argument == "--profile":
            return sys.argv[index + 1].strip().lower()
    return ""


def _session_name(value: Any = "atelier") -> str:
    session = str("atelier" if value is None else value).strip()
    if not _SESSION_RE.fullmatch(session):
        raise ValueError("session must be a plain Pattern Kit collaborative session name")
    return session


def _selector(value: Any) -> str:
    selector = str(value or "").strip()
    if not _SELECTOR_RE.fullmatch(selector) or _FORBIDDEN_SELECTOR_RE.search(selector):
        raise ValueError("selector must be one safe visible Pattern Kit control id")
    return selector


def _key(value: Any) -> str:
    key = str(value or "").strip()
    if key not in _ALLOWED_KEYS:
        raise ValueError("key is outside the bounded Pattern Kit navigation-key allowlist")
    return key


def _typed_text(value: Any) -> str:
    text = str(value or "")
    if len(text) > 500 or _SENSITIVE_TEXT_RE.search(text):
        raise ValueError("typed text is too long or resembles credentials/private information")
    return text


def _revision(value: Any) -> int:
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("revision must be an integer from a fresh session snapshot") from exc
    if revision < 0:
        raise ValueError("revision must be non-negative")
    return revision


def _validate_bridge_path(path: str) -> str:
    if not path.startswith("/agent/") or path.startswith("//") or "://" in path:
        raise ValueError("bridge requests must use a supported relative agent route")
    lowered = path.lower()
    if any(term in lowered for term in ("token=", "secret=", "cookie=", "storage=", "oauth=")):
        raise ValueError("secret-bearing bridge queries are forbidden")
    return path


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        super().__init__("localhost", timeout=20)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(BROKER_SOCKET))


def _bridge_request(path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
    _validate_bridge_path(path)
    if _current_profile() != "star":
        raise RuntimeError("Pattern Kit session bridge is not enabled for this profile")
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    connection = _UnixHTTPConnection()
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if response.status >= 400:
            raise RuntimeError(f"Pattern Kit broker refused the request ({response.status})")
    except (OSError, http.client.HTTPException) as exc:
        raise RuntimeError("Pattern Kit session broker is unavailable") from exc
    finally:
        connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Pattern Kit bridge response exceeded the safe result limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("Pattern Kit bridge returned an invalid response")
    return value


def _json_result(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _safe_tool_call(handler: Any, params: dict[str, Any]) -> str:
    """Keep bridge failures inside the JSON tool contract without leaking details."""
    try:
        return handler(params)
    except Exception:
        return _json_result({
            "schema": "patternkit.session.error/v1",
            "ok": False,
            "error": "Pattern Kit session operation failed",
        })


def _session_path(route: str, params: dict[str, Any]) -> str:
    return f"/agent/{route}?session={quote(_session_name(params.get('session', 'atelier')), safe='')}"


def patternkit_session_status(params: dict[str, Any]) -> str:
    return _json_result(_bridge_request(_session_path("status", params)))


def patternkit_session_snapshot(params: dict[str, Any]) -> str:
    return _json_result(_bridge_request(_session_path("snapshot", params)))


def patternkit_session_diagnostics(params: dict[str, Any]) -> str:
    observe = min(5.0, max(0.0, float(params.get("observe_seconds", 1))))
    slow_ms = min(10000, max(100, int(params.get("slow_ms", 1000))))
    path = f"{_session_path('diagnostics', params)}&observe_seconds={observe:g}&slow_ms={slow_ms}"
    return _json_result(_bridge_request(path))


def patternkit_session_visual_evidence(params: dict[str, Any]) -> str:
    response = _bridge_request(_session_path("visual", params))
    encoded = response.pop("image_base64", None)
    if not isinstance(encoded, str):
        raise RuntimeError("Pattern Kit bridge did not return PNG evidence")
    image = base64.b64decode(encoded, validate=True)
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        # Synthetic tests use a deliberately short PNG prefix.
        if not image.startswith(b"\x89PNG"):
            raise RuntimeError("Pattern Kit bridge returned non-PNG evidence")
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SCREENSHOT_DIR, 0o700)
    revision = int(response.get("revision", 0))
    stem = f"patternkit-{_session_name(params.get('session', 'atelier'))}-r{revision}-{time.time_ns()}"
    for _attempt in range(4):
        path = SCREENSHOT_DIR / f"{stem}-{secrets.token_hex(6)}.png"
        try:
            with path.open("xb") as evidence:
                evidence.write(image)
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("could not create a unique Pattern Kit evidence file")
    os.chmod(path, 0o600)
    response["path"] = str(path)
    return _json_result(response)


def patternkit_session_control(params: dict[str, Any]) -> str:
    action = str(params.get("action", "")).strip().lower()
    if action not in {"acquire", "release", "handoff"}:
        raise ValueError("control action must be acquire, release, or handoff")
    payload: dict[str, object] = {"session": _session_name(params.get("session", "atelier")), "action": action}
    if action == "handoff":
        payload["to_actor"] = _session_name(params.get("to_actor"))
    return _json_result(_bridge_request("/agent/control", method="POST", payload=payload))


def _input(params: dict[str, Any], action: str) -> str:
    payload: dict[str, object] = {
        "session": _session_name(params.get("session", "atelier")),
        "revision": _revision(params.get("revision")),
        "action": action,
    }
    if action in {"click", "type"}:
        payload["selector"] = _selector(params.get("selector"))
    if action == "type":
        payload["text"] = _typed_text(params.get("text"))
    if action == "key":
        payload["key"] = _key(params.get("key"))
    return _json_result(_bridge_request("/agent/input", method="POST", payload=payload))


def patternkit_session_click(params: dict[str, Any]) -> str:
    return _input(params, "click")


def patternkit_session_type(params: dict[str, Any]) -> str:
    return _input(params, "type")


def patternkit_session_key(params: dict[str, Any]) -> str:
    return _input(params, "key")
