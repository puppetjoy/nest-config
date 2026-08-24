#!/usr/bin/env python3
"""Visible, fail-closed active-tab binding and agent bridge for Pattern Kit."""

from __future__ import annotations

import base64
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen

HOST = os.environ.get("PATTERNKIT_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("PATTERNKIT_BRIDGE_PORT", "8766"))
TARGET_ORIGIN = os.environ.get("PATTERNKIT_ORIGIN", "https://patternkit.eyrie").rstrip("/")
STUDIO_PROXY = os.environ.get("PATTERNKIT_STUDIO_PROXY", "")
STATE_PATH = Path(os.environ.get("PATTERNKIT_BINDING_STATE", "/home/kasm-user/.patternkit-workbench/binding.json"))
DISPLAY = os.environ.get("DISPLAY", ":1")
NODE_NAME = os.environ.get("PATTERNKIT_NODE_NAME", "")
BRIDGE_TOKEN = os.environ.get("PATTERNKIT_BRIDGE_TOKEN", "")
AGENT_TOKEN = os.environ.get("PATTERNKIT_AGENT_TOKEN", "")
STUDIO_BRIDGE_TOKEN = os.environ.get("PATTERNKIT_STUDIO_BRIDGE_TOKEN", "")
BIDI_HOST = os.environ.get("PATTERNKIT_BIDI_HOST", "127.0.0.1")
BIDI_PORT = int(os.environ.get("PATTERNKIT_BIDI_PORT", "9222"))
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SELECTOR_RE = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,63}$")
_FORBIDDEN_CONTROL = re.compile(
    r"render|save|export|download|upload|source|profile|git|password|token|secret|cookie|storage|oauth|credential|measurement",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\d[ -]*?){12,19}|\b(?:authorization|bearer|credential|password|passkey|token|secret|cookie|oauth|private)\b)",
    re.IGNORECASE,
)
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PUBLIC_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_ALLOWED_KEYS = {"ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Tab", "Space"}
_PUBLIC_DIAGNOSTIC_WORDS = {
    "api", "app", "at", "browser", "canvas", "connected", "connection",
    "control", "diagnostic", "disconnected", "error", "failed", "failure",
    "fetch", "for", "from", "in", "invalid", "lease", "loaded", "loading",
    "network", "of", "on", "pattern", "patternkit", "ready", "reconnect", "redacted",
    "render", "rendering", "request", "response", "retry", "revision",
    "session", "slow", "status", "studio", "the", "timeout", "to", "value",
    "warning", "websocket", "with",
}
_WEBDRIVER_KEYS = {
    "ArrowUp": "\ue013",
    "ArrowDown": "\ue015",
    "ArrowLeft": "\ue012",
    "ArrowRight": "\ue014",
    "Enter": "\ue007",
    "Escape": "\ue00c",
    "Tab": "\ue004",
    "Space": "\ue00d",
}
_AGENT_OPERATION_LOCK = threading.Lock()


class AgentRequestError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


class _WebSocket:
    """Small RFC 6455 client sufficient for Firefox's loopback BiDi endpoint."""

    def __init__(self, host: str, port: int, path: str = "/session") -> None:
        self.sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._read_headers()
        if not response.startswith(b"HTTP/1.1 101"):
            self.sock.close()
            raise RuntimeError("Firefox BiDi WebSocket handshake failed")

    def _read_headers(self) -> bytes:
        data = bytearray()
        while b"\r\n\r\n" not in data and len(data) < 16384:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)

    def _exact(self, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise RuntimeError("Firefox closed the BiDi WebSocket")
            data.extend(chunk)
        return bytes(data)

    def send_json(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        first = bytearray([0x81])
        length = len(payload)
        if length < 126:
            first.append(0x80 | length)
        elif length <= 65535:
            first.extend([0x80 | 126])
            first.extend(struct.pack("!H", length))
        else:
            first.extend([0x80 | 127])
            first.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        first.extend(mask)
        first.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(first)

    def recv_json(self, timeout: float = 10) -> dict[str, Any]:
        self.sock.settimeout(timeout)
        while True:
            header = self._exact(2)
            opcode = header[0] & 0x0F
            length = header[1] & 0x7F
            masked = bool(header[1] & 0x80)
            if length == 126:
                length = struct.unpack("!H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if masked else b""
            payload = self._exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("Firefox closed the BiDi session")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode != 0x1:
                continue
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise RuntimeError("Firefox returned an invalid BiDi message")
            return value

    def _send_control(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        frame = bytearray([0x80 | opcode, 0x80 | len(payload)])
        frame.extend(mask)
        frame.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(frame)

    def close(self) -> None:
        try:
            self._send_control(0x8, b"")
        except OSError:
            pass
        self.sock.close()


class _Bidi:
    def __init__(self) -> None:
        self.ws = _WebSocket(BIDI_HOST, BIDI_PORT)
        self.next_id = 1
        self.events: list[dict[str, Any]] = []
        self.call("session.new", {"capabilities": {"alwaysMatch": {}}})

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        call_id = self.next_id
        self.next_id += 1
        self.ws.send_json({"id": call_id, "method": method, "params": params or {}})
        while True:
            result = self.ws.recv_json()
            if result.get("id") != call_id:
                if result.get("type") == "event" or ("method" in result and "id" not in result):
                    self.events.append(result)
                continue
            if result.get("type") == "error" or result.get("error"):
                raise RuntimeError(f"Firefox BiDi {method} failed: {result.get('message') or result.get('error')}")
            value = result.get("result") or {}
            return value if isinstance(value, dict) else {}

    def event(self, timeout: float) -> dict[str, Any] | None:
        if self.events:
            return self.events.pop(0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = self.ws.recv_json(max(0.05, deadline - time.monotonic()))
            except socket.timeout:
                return None
            if value.get("type") == "event" or ("method" in value and "id" not in value):
                return value
        return None

    def close(self) -> None:
        try:
            self.call("session.end")
        except Exception:
            pass
        self.ws.close()

    def __enter__(self) -> "_Bidi":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _bidi_value(value: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return None
    if "value" not in value:
        return None
    raw = value.get("value")
    if value.get("type") == "array" and isinstance(raw, list):
        return [_bidi_value(item) if isinstance(item, dict) else item for item in raw]
    if value.get("type") == "object" and isinstance(raw, list):
        return {
            str(_bidi_value(item[0]) if isinstance(item[0], dict) else item[0]):
            _bidi_value(item[1]) if isinstance(item[1], dict) else item[1]
            for item in raw if isinstance(item, list) and len(item) == 2
        }
    return raw


def _is_loopback(address: str) -> bool:
    return address in {"127.0.0.1", "::1"}


def _browser_start_identity() -> str | None:
    try:
        output = subprocess.check_output(["pgrep", "-o", "firefox"], text=True, timeout=2).strip()
        fields = Path(f"/proc/{int(output)}/stat").read_text().split()
        return f"{output}:{fields[21]}"
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _is_target_url(raw_url: str) -> bool:
    parsed = urlsplit(raw_url)
    target = urlsplit(TARGET_ORIGIN)
    return parsed.scheme == target.scheme and parsed.netloc == target.netloc


def _contexts_are_isolated(contexts: list[dict[str, str]]) -> bool:
    for context in contexts:
        parsed = urlsplit(str(context.get("url") or ""))
        if parsed.scheme in {"http", "https"} and not _is_target_url(parsed.geturl()):
            return False
    return True


def _browser_contexts(bidi: _Bidi | None = None) -> list[dict[str, str]]:
    own = bidi is None
    session = bidi or _Bidi()
    try:
        contexts = session.call("browsingContext.getTree").get("contexts") or []
        result = []
        for context in contexts:
            if not isinstance(context, dict) or not context.get("context"):
                continue
            context_id = str(context["context"])
            raw_url = str(context.get("url") or "")
            title = ""
            if _is_target_url(raw_url):
                title_result = session.call(
                    "script.evaluate",
                    {
                        "expression": "document.title",
                        "target": {"context": context_id},
                        "awaitPromise": False,
                        "resultOwnership": "none",
                    },
                )
                title = str(_bidi_value(title_result.get("result") or {}) or "")
            result.append({"id": context_id, "url": raw_url, "title": title})
        return result
    finally:
        if own:
            session.close()


def _active_context(bidi: _Bidi | None = None, *, require_isolated: bool = True) -> dict[str, str] | None:
    env = {**os.environ, "DISPLAY": DISPLAY}
    try:
        window = subprocess.check_output(["xdotool", "getactivewindow"], env=env, text=True, timeout=3).strip()
        window_class = subprocess.check_output(["xdotool", "getwindowclassname", window], env=env, text=True, timeout=3).strip().lower()
        if "firefox" not in window_class:
            return None
        active_title = subprocess.check_output(["xdotool", "getwindowname", window], env=env, text=True, timeout=3).strip()
        browser_title = active_title
        for suffix in (" — Mozilla Firefox", " - Mozilla Firefox"):
            if browser_title.endswith(suffix):
                browser_title = browser_title[:-len(suffix)]
                break
        contexts = _browser_contexts(bidi)
        if require_isolated and not _contexts_are_isolated(contexts):
            return None
        matches = [item for item in contexts if item.get("title") == browser_title]
        if len(matches) != 1:
            return None
        value = str(matches[0].get("url", ""))
        target_id = str(matches[0].get("id", "")).strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not target_id:
            return None
        return {"id": target_id, "url": value}
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError, IndexError):
        return None


def _read_state() -> dict[str, object] | None:
    try:
        value = json.loads(STATE_PATH.read_text())
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(value: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(STATE_PATH)


def _binding_matches(state: dict[str, object] | None, process: str | None, active_context: dict[str, str] | None) -> tuple[bool, bool]:
    active_url = active_context.get("url") if active_context else None
    parsed_active = urlsplit(active_url) if active_url else None
    parsed_target = urlsplit(TARGET_ORIGIN)
    active_origin_matches = bool(parsed_active and parsed_active.scheme == parsed_target.scheme and parsed_active.netloc == parsed_target.netloc)
    active_bindings = parse_qs(parsed_active.query).get("pk-share", []) if parsed_active else []
    active_sessions = parse_qs(parsed_active.query).get("session", []) if parsed_active else []
    valid = bool(
        state
        and process
        and state.get("target_id")
        and state.get("browser_start_identity") == process
        and active_origin_matches
        and len(active_bindings) == 1
        and len(active_sessions) == 1
        and secrets.compare_digest(str(active_sessions[0]), str(state.get("session", "")))
        and secrets.compare_digest(str(active_bindings[0]), str(state.get("binding_id", "")))
        and secrets.compare_digest(str((active_context or {}).get("id", "")), str(state.get("target_id", "")))
    )
    return valid, active_origin_matches


def _validated_state() -> dict[str, object]:
    state = _read_state()
    process = _browser_start_identity()
    active_context = _active_context()
    valid, active_origin_matches = _binding_matches(state, process, active_context)
    return {
        "schema": "patternkit.workbench.binding/v1",
        "bound": valid,
        "binding_id": state.get("binding_id") if valid and state else None,
        "selected_context": state.get("target_id") if valid and state else None,
        "origin": TARGET_ORIGIN,
        "node": NODE_NAME,
        "browser_generation": process,
        "active_origin_matches": active_origin_matches,
        "session": state.get("session") if valid and state else None,
        "reason": "verified-active-tab" if valid else "explicit-share-required",
    }


def _public_binding(binding: dict[str, object]) -> dict[str, object]:
    """Publish verification booleans without context IDs, URLs, or host details."""
    bound = bool(binding.get("bound"))
    return {
        "schema": "patternkit.workbench.binding/v1",
        "bound": bound,
        "active_context_verified": bound,
        "patternkit_origin_verified": bool(binding.get("active_origin_matches")) and bound,
        "isolated_browser_verified": bound,
        "reason": str(binding.get("reason") or "explicit-share-required"),
    }


def _require_exact_binding(state: dict[str, object] | None = None, session: str | None = None) -> dict[str, object]:
    current = state or _validated_state()
    if not (
        current.get("bound")
        and current.get("selected_context")
        and current.get("browser_generation")
        and current.get("active_origin_matches")
        and current.get("session")
    ):
        raise AgentRequestError(HTTPStatus.CONFLICT, "exact visibly shared Pattern Kit tab is not verified")
    if session is not None and not secrets.compare_digest(str(current.get("session")), _session_name(session)):
        raise AgentRequestError(HTTPStatus.CONFLICT, "requested session is not the visibly shared Pattern Kit session")
    return current


def _session_name(value: Any) -> str:
    session = str(value or "").strip()
    if not _SESSION_RE.fullmatch(session):
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid Pattern Kit session name")
    return session


def _studio_api_path(route: str, session: str) -> str:
    name = quote(_session_name(session), safe="")
    if route == "session":
        return f"/api/session?name={name}"
    if route == "diagnostics":
        return f"/api/diagnostics/capture?name={name}"
    if route == "control":
        return "/api/session/control"
    raise AgentRequestError(HTTPStatus.BAD_REQUEST, "unsupported Pattern Kit Studio API route")


def _decode_studio_response(status: int, headers: Any, body: bytes) -> dict[str, object]:
    if status < 200 or status >= 300:
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, f"Pattern Kit Studio API returned HTTP {status}")
    content_type = str(headers.get("Content-Type", headers.get("content-type", ""))).lower()
    if "application/json" not in content_type:
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Pattern Kit Studio API returned a login or non-JSON response")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Pattern Kit Studio API returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Pattern Kit Studio API returned an invalid document")
    return value


def _studio_request(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    if not STUDIO_BRIDGE_TOKEN:
        raise AgentRequestError(HTTPStatus.SERVICE_UNAVAILABLE, "Pattern Kit Studio bridge identity is unavailable")
    if not path.startswith("/api/") or "://" in path or any(term in path.lower() for term in ("token=", "cookie=", "secret=")):
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "unsupported Pattern Kit Studio API request")
    proxy = ProxyHandler({"http": STUDIO_PROXY, "https": STUDIO_PROXY} if STUDIO_PROXY else {})
    opener = build_opener(proxy, _NoRedirect())
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    request = Request(
        f"{TARGET_ORIGIN}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-PatternKit-Bridge-Token": STUDIO_BRIDGE_TOKEN,
        },
    )
    try:
        with opener.open(request, timeout=10) as response:
            return _decode_studio_response(response.status, response.headers, response.read(1048577))
    except HTTPError as exc:
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, f"Pattern Kit Studio API returned HTTP {exc.code}") from None


def _public_identifier(value: object) -> str:
    text = str(value or "")
    if not _PUBLIC_IDENTIFIER.fullmatch(text) or _SENSITIVE_VALUE.search(text):
        return "[REDACTED]"
    return text


def _public_target(value: object) -> str:
    text = str(value or "")[:200]
    if not _PUBLIC_TARGET.fullmatch(text) or _SENSITIVE_VALUE.search(text):
        return "[REDACTED]"
    return text


def _public_actor(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"joy", "star"}:
        return text
    return "human"


def _public_presence(value: dict[object, object]) -> list[str]:
    return sorted({actor for raw in value for actor in [_public_actor(raw)] if actor})


def _compact_session(value: dict[str, object]) -> dict[str, object]:
    control = value.get("control") if isinstance(value.get("control"), dict) else {}
    presence = value.get("presence") if isinstance(value.get("presence"), dict) else {}
    return {
        "name": _public_identifier(value.get("name")),
        "revision": int(value.get("revision") or 0),
        "presence": _public_presence(presence),
        "control_owner": _public_actor(control.get("holder")),
        "control_expires_at": control.get("expires_at"),
        "star_present": any(str(actor).lower() == "star" for actor in presence),
        "star_has_control": str(control.get("holder") or "").lower() == "star",
    }


def _require_star_lease(snapshot: dict[str, object], expected_revision: int) -> None:
    control = snapshot.get("control") if isinstance(snapshot.get("control"), dict) else {}
    if int(snapshot.get("revision") or 0) != int(expected_revision):
        raise AgentRequestError(HTTPStatus.CONFLICT, "stale Pattern Kit session revision")
    if control.get("holder") != "star":
        raise AgentRequestError(HTTPStatus.LOCKED, "Star does not hold the visible Pattern Kit control lease")
    expires_at = control.get("expires_at")
    if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
        raise AgentRequestError(HTTPStatus.LOCKED, "Star's visible Pattern Kit control lease expired")


def _safe_selector(value: Any) -> str:
    selector = str(value or "").strip()
    if not _SELECTOR_RE.fullmatch(selector) or _FORBIDDEN_CONTROL.search(selector):
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "selector is not a safe Pattern Kit control id")
    return selector


def _safe_key(value: Any) -> str:
    key = str(value or "").strip()
    if key not in _ALLOWED_KEYS:
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "key is outside the Pattern Kit navigation allowlist")
    return key


def _safe_text(value: Any) -> str:
    text = str(value or "")
    if len(text) > 500 or re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\d[ -]*?){12,19}|\b(?:password|token|secret|cookie|oauth|cvv|cvc)\b", text, re.I):
        raise AgentRequestError(HTTPStatus.BAD_REQUEST, "typed value resembles credentials or private information")
    return text


def _exact_bidi_context(bidi: _Bidi, binding: dict[str, object]) -> dict[str, str]:
    target_id = str(binding["selected_context"])
    active_context = _active_context(bidi)
    if (
        active_context is None
        or active_context.get("id") != target_id
        or not _binding_matches(_read_state(), _browser_start_identity(), active_context)[0]
    ):
        raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit tab identity changed during browser attach")
    return active_context


def _studio_bidi_context(bidi: _Bidi, binding: dict[str, object]) -> dict[str, str]:
    """Resolve the Studio iframe below the revalidated, visibly bound tab."""
    top = _exact_bidi_context(bidi, binding)
    roots = bidi.call("browsingContext.getTree", {"root": top["id"]}).get("contexts") or []
    matches: list[dict[str, str]] = []

    def visit(contexts: list[object]) -> None:
        for context in contexts:
            if not isinstance(context, dict):
                continue
            raw_url = str(context.get("url") or "")
            parsed = urlsplit(raw_url)
            target = urlsplit(TARGET_ORIGIN)
            if (
                context.get("context")
                and parsed.scheme == target.scheme
                and parsed.netloc == target.netloc
                and parsed.path in {"/studio", "/studio/"}
            ):
                matches.append({"id": str(context["context"]), "url": raw_url})
            children = context.get("children")
            if isinstance(children, list):
                visit(children)

    visit(roots if isinstance(roots, list) else [])
    if len(matches) != 1:
        raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit Studio frame identity is not unique")
    return matches[0]


def _evaluate(bidi: _Bidi, context_id: str, expression: str) -> Any:
    result = bidi.call(
        "script.evaluate",
        {
            "expression": expression,
            "target": {"context": context_id},
            "awaitPromise": True,
            "resultOwnership": "none",
        },
    )
    if result.get("exceptionDetails"):
        raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit browser operation failed")
    return _bidi_value(result.get("result") or {})


def _safe_element_expression(selector: str) -> str:
    encoded = json.dumps(selector)
    return f"""(() => {{
      const el = document.querySelector({encoded});
      if (!el) return {{ok:false, reason:'not-found'}};
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      const text = [el.id, el.name, el.type, el.getAttribute('aria-label'), el.textContent, el.getAttribute('href'), el.getAttribute('action'), el.closest('label')?.textContent].filter(Boolean).join(' ');
      if (r.width <= 0 || r.height <= 0 || style.visibility === 'hidden' || style.display === 'none') return {{ok:false, reason:'not-visible'}};
      if (el.closest('#measurementsRoot')) return {{ok:false, reason:'private-measurement-control'}};
      if (/render|save|export|download|upload|source|profile|git|password|token|secret|cookie|storage|oauth|credential|measurement/i.test(text)) return {{ok:false, reason:'unsafe-control'}};
      return {{ok:true}};
    }})()"""


def _browser_request(event: dict[str, Any]) -> tuple[str, str, str]:
    params = event.get("params") if isinstance(event.get("params"), dict) else {}
    request = params.get("request") if isinstance(params.get("request"), dict) else {}
    return (
        str(request.get("request") or params.get("requestId") or ""),
        str(request.get("method") or "").upper(),
        str(request.get("url") or ""),
    )


def _continue_as_star(
    bidi: _Bidi,
    event: dict[str, Any],
    *,
    intercept: str,
    operation: str,
    session: str,
    revision: int,
) -> tuple[str, str, str] | None:
    params = event.get("params") if isinstance(event.get("params"), dict) else {}
    intercepts = params.get("intercepts") if isinstance(params.get("intercepts"), list) else []
    if params.get("isBlocked") is not True or intercept not in intercepts:
        return None
    request_id, method, raw_url = _browser_request(event)
    parsed = urlsplit(raw_url)
    target = urlsplit(TARGET_ORIGIN)
    allowed = (
        request_id
        and method == "POST"
        and parsed.scheme == target.scheme
        and parsed.netloc == target.netloc
        # Session state is the only browser mutation whose supported API
        # atomically verifies both Star's lease and the expected revision.
        # Rendering stays inspectable through diagnostics, but is not a Star
        # control operation until /api/render offers the same server contract.
        and parsed.path == "/api/session/state"
    )
    request = params.get("request") if isinstance(params.get("request"), dict) else {}
    headers = request.get("headers") if isinstance(request.get("headers"), list) else []
    if allowed:
        guarded_url = urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode({"pk-agent-operation": operation, "pk-session": session, "pk-revision": revision}),
            "",
        ))
        headers = [header for header in headers if str(header.get("name") if isinstance(header, dict) else "").lower() != "x-patternkit-bridge-token"]
        if not STUDIO_BRIDGE_TOKEN:
            raise AgentRequestError(HTTPStatus.SERVICE_UNAVAILABLE, "Pattern Kit Studio bridge identity is unavailable")
        headers.append({"name": "X-PatternKit-Bridge-Token", "value": {"type": "string", "value": STUDIO_BRIDGE_TOKEN}})
        bidi.call("network.continueRequest", {"request": request_id, "url": guarded_url, "headers": headers})
        return request_id, parsed.path, operation
    if request_id:
        bidi.call("network.failRequest", {"request": request_id})
        raise AgentRequestError(HTTPStatus.CONFLICT, "Firefox attempted a request outside the bounded Pattern Kit operation")
    raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Firefox returned an invalid intercepted request")


def _browser_response_receipt(
    event: dict[str, Any],
    guarded: tuple[str, str, str],
    *,
    session: str,
    revision: int,
) -> dict[str, object] | None:
    request_id, method, response_url = _browser_request(event)
    parsed = urlsplit(response_url)
    target = urlsplit(TARGET_ORIGIN)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not (
        request_id == guarded[0]
        and method == "POST"
        and parsed.scheme == target.scheme
        and parsed.netloc == target.netloc
        and parsed.path == guarded[1]
        and query.get("pk-agent-operation") == [guarded[2]]
        and query.get("pk-session") == [session]
        and query.get("pk-revision") == [str(revision)]
    ):
        return None
    params = event.get("params") if isinstance(event.get("params"), dict) else {}
    response = params.get("response") if isinstance(params.get("response"), dict) else {}
    return {
        "status": int(response.get("status") or 0),
        "path": guarded[1],
        "operation": guarded[2],
        "actor": "star",
        "session": session,
        "revision": revision,
    }


def _browser_input(
    binding: dict[str, object],
    action: str,
    selector: str | None,
    text: str | None,
    key: str | None,
    *,
    session: str,
    revision: int,
) -> dict[str, object]:
    with _Bidi() as bidi:
        context = _studio_bidi_context(bidi, binding)
        context_id = context["id"]
        if selector:
            safety = _evaluate(bidi, context_id, _safe_element_expression(selector))
        else:
            safety = _evaluate(bidi, context_id, _safe_element_expression("#" + str(_evaluate(bidi, context_id, "document.activeElement && document.activeElement.id"))))
        if not isinstance(safety, dict) or not safety.get("ok"):
            raise AgentRequestError(HTTPStatus.CONFLICT, f"Pattern Kit control is unsafe or unavailable: {(safety or {}).get('reason', 'unknown') if isinstance(safety, dict) else 'unknown'}")
        operation = secrets.token_urlsafe(18)
        bidi.call(
            "session.subscribe",
            {
                "events": ["network.beforeRequestSent", "network.responseCompleted"],
                "contexts": [context_id],
            },
        )
        intercept = bidi.call(
            "network.addIntercept",
            {
                "phases": ["beforeRequestSent"],
                "contexts": [context_id],
            },
        ).get("intercept")
        if not intercept:
            raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Firefox did not install the bounded Pattern Kit request guard")
        try:
            if action == "click" and selector:
                _evaluate(bidi, context_id, f"document.querySelector({json.dumps(selector)}).click(); true")
            elif action == "type" and selector:
                expression = f"""(() => {{ const el=document.querySelector({json.dumps(selector)}); el.focus(); el.value={json.dumps(text)}; el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); return true; }})()"""
                _evaluate(bidi, context_id, expression)
            elif action == "key" and key:
                bidi.call(
                    "input.performActions",
                    {
                        "context": context_id,
                        "actions": [{
                            "type": "key",
                            "id": "patternkit-star-keyboard",
                            "actions": [
                                {"type": "keyDown", "value": _WEBDRIVER_KEYS[key]},
                                {"type": "keyUp", "value": _WEBDRIVER_KEYS[key]},
                            ],
                        }],
                    },
                )
            else:
                raise AgentRequestError(HTTPStatus.BAD_REQUEST, "unsupported Pattern Kit input action")

            deadline = time.monotonic() + (1.0 if action == "key" else 5.0)
            guarded: tuple[str, str, str] | None = None
            while time.monotonic() < deadline:
                event = bidi.event(deadline - time.monotonic())
                if event is None:
                    break
                if event.get("method") == "network.beforeRequestSent":
                    continued = _continue_as_star(
                        bidi,
                        event,
                        intercept=str(intercept),
                        operation=operation,
                        session=session,
                        revision=revision,
                    )
                    if continued:
                        if guarded and continued[0] != guarded[0]:
                            bidi.call("network.failRequest", {"request": continued[0]})
                            raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit emitted more than one controlled request")
                        guarded = continued
                elif event.get("method") == "network.responseCompleted" and guarded:
                    receipt = _browser_response_receipt(event, guarded, session=session, revision=revision)
                    if receipt is not None:
                        return receipt
            raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit did not acknowledge the browser action")
        finally:
            bidi.call("network.removeIntercept", {"intercept": intercept})


def _sanitize_diagnostic_message(value: object) -> str:
    message = str(value or "")[:500]
    if _SENSITIVE_VALUE.search(message) or re.search(r"measurement|profile", message, re.I):
        return "[REDACTED]"
    message = re.sub(r"https?://[^\s]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d+(?:[ .:-]\d+)*\b", "[REDACTED]", message)

    def public_word(match: re.Match[str]) -> str:
        word = match.group(0)
        return word if word.lower() in _PUBLIC_DIAGNOSTIC_WORDS else "[REDACTED]"

    return re.sub(r"[A-Za-z][A-Za-z0-9._-]*", public_word, message)


def _sanitize_browser_event(value: dict[str, object], *, slow_ms: int) -> dict[str, object]:
    raw_url = str(value.get("url") or "")
    parsed_url = urlsplit(raw_url)
    origin_scope = "patternkit" if _is_target_url(raw_url) else ("external" if parsed_url.scheme in {"http", "https"} else "none")
    status = int(value.get("status") or 0)
    duration = max(0, int(value.get("duration_ms") or 0))
    message = _sanitize_diagnostic_message(value.get("message"))
    return {
        "type": str(value.get("type") or "unknown")[:80],
        "origin_scope": origin_scope,
        "status": status,
        "duration_ms": duration,
        "failed": bool(value.get("failed") or status >= 400),
        "slow": duration >= slow_ms,
        "level": str(value.get("level") or "")[:20],
        "message": message,
    }


def _sanitize_app_diagnostic(value: dict[str, object]) -> dict[str, object]:
    """Project the supported diagnostic contract onto a defensive allowlist."""
    session = value.get("session") if isinstance(value.get("session"), dict) else {}
    state = session.get("state") if isinstance(session.get("state"), dict) else {}
    selection = state.get("session") if isinstance(state.get("session"), dict) else {}
    presence = session.get("presence") if isinstance(session.get("presence"), dict) else {}
    control = session.get("control") if isinstance(session.get("control"), dict) else {}
    return {
        "schema": "patternkit.agent.app-diagnostic/v1",
        "captured_at": value.get("captured_at") if isinstance(value.get("captured_at"), (int, float)) else None,
        "session": {
            "name": _public_identifier(session.get("name")),
            "revision": int(session.get("revision") or 0),
            "target": _public_target(selection.get("target") or state.get("target")),
            "presence": _public_presence(presence),
            "control_owner": _public_actor(control.get("holder")),
            "control_expires_at": control.get("expires_at") if isinstance(control.get("expires_at"), (int, float)) else None,
        },
    }


def _verify_browser_receipt(
    session: str,
    expected_revision: int,
    before: dict[str, object],
    after: dict[str, object],
    receipt: dict[str, object],
    *,
    mutates_session: bool,
) -> None:
    """Require an app-acknowledged Star request, never just a DOM success."""
    _require_star_lease(before, expected_revision)
    if (
        receipt.get("actor") != "star"
        or receipt.get("session") != session
        or int(receipt.get("revision") or -1) != expected_revision
        or not 200 <= int(receipt.get("status") or 0) < 300
    ):
        raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit did not verify the browser action as Star")
    expected_after_revision = expected_revision + 1 if mutates_session else expected_revision
    if int(after.get("revision") or 0) != expected_after_revision:
        raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit session revision did not atomically match the browser action")
    _require_star_lease(after, expected_after_revision)


def _execute_agent_input(binding: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    """Execute one lease-bound browser operation as a serialized transaction."""
    with _AGENT_OPERATION_LOCK:
        session = _session_name(payload.get("session"))
        action = str(payload.get("action") or "").lower()
        if action not in {"click", "type", "key"}:
            raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid input action")
        revision = int(payload.get("revision"))
        studio = _studio_request("GET", _studio_api_path("session", session))
        _require_star_lease(studio, revision)
        selector = _safe_selector(payload.get("selector")) if action in {"click", "type"} else None
        text = _safe_text(payload.get("text")) if action == "type" else None
        key = _safe_key(payload.get("key")) if action == "key" else None
        receipt = _browser_input(
            binding,
            action,
            selector,
            text,
            key,
            session=session,
            revision=revision,
        )
        current = _studio_request("GET", _studio_api_path("session", session))
        _verify_browser_receipt(
            session,
            revision,
            studio,
            current,
            receipt,
            mutates_session=receipt.get("path") == "/api/session/state",
        )
        return {
            "schema": "patternkit.agent.input/v1",
            "ok": True,
            "action": action,
            "session": _compact_session(current),
        }


def _execute_agent_control(payload: dict[str, object]) -> dict[str, object]:
    """Serialize lease changes with all lease-bound browser transactions."""
    with _AGENT_OPERATION_LOCK:
        session = _session_name(payload.get("session"))
        action = str(payload.get("action") or "").lower()
        if action not in {"acquire", "release", "handoff"}:
            raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid control action")
        request_payload: dict[str, object] = {"name": session, "action": action}
        if action == "handoff":
            request_payload["to_actor"] = _session_name(payload.get("to_actor"))
        result = _studio_request("POST", _studio_api_path("control", session), request_payload)
        return {"schema": "patternkit.agent.control/v1", "ok": True, "session": _compact_session(result)}


def _agent_status(session: str) -> dict[str, object]:
    binding = _require_exact_binding(session=session)
    studio = _studio_request("GET", _studio_api_path("session", session))
    return {
        "schema": "patternkit.agent.status/v1",
        "ok": True,
        "binding": _public_binding(binding),
        "session": _compact_session(studio),
    }


def _agent_runtime_canary() -> dict[str, object]:
    """Exercise the live Firefox BiDi session and return only safe counts."""
    try:
        with _Bidi() as bidi:
            contexts = _browser_contexts(bidi)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Firefox BiDi runtime is unavailable") from exc
    target = urlsplit(TARGET_ORIGIN)
    patternkit_count = 0
    for context in contexts:
        parsed = urlsplit(str(context.get("url") or ""))
        if parsed.scheme == target.scheme and parsed.netloc == target.netloc:
            patternkit_count += 1
    if not _contexts_are_isolated(contexts):
        raise AgentRequestError(HTTPStatus.CONFLICT, "isolated Firefox contains an external web origin")
    return {
        "schema": "patternkit.agent.runtime-canary/v1",
        "ok": True,
        "bidi": "ready",
        "context_count": len(contexts),
        "patternkit_context_count": patternkit_count,
        "external_context_count": 0,
    }


def _agent_snapshot(session: str) -> dict[str, object]:
    binding = _require_exact_binding(session=session)
    _studio_request("GET", _studio_api_path("session", session))
    diagnostic = _studio_request("GET", _studio_api_path("diagnostics", session))
    return {
        "schema": "patternkit.agent.snapshot/v1",
        "ok": True,
        "binding": _public_binding(binding),
        "snapshot": _sanitize_app_diagnostic(diagnostic),
    }


def _agent_visual(session: str) -> dict[str, object]:
    binding = _require_exact_binding(session=session)
    studio = _studio_request("GET", _studio_api_path("session", session))
    with _Bidi() as bidi:
        context = _studio_bidi_context(bidi, binding)
        context_id = context["id"]
        bounds = _evaluate(bidi, context_id, "(() => { const el=document.querySelector('#svgMount > svg'); if(!el) return null; const r=el.getBoundingClientRect(); const left=Math.max(0,r.left), top=Math.max(0,r.top), right=Math.min(innerWidth,r.right), bottom=Math.min(innerHeight,r.bottom); if(right-left < 1 || bottom-top < 1) return null; return {x:left,y:top,width:right-left,height:bottom-top}; })()")
        if not isinstance(bounds, dict):
            raise AgentRequestError(HTTPStatus.CONFLICT, "Pattern Kit canvas is not visible")
        capture = bidi.call(
            "browsingContext.captureScreenshot",
            {"context": context_id, "origin": "viewport", "clip": {"type": "box", **bounds}},
        )
    encoded = str(capture.get("data") or "")
    if not encoded:
        raise AgentRequestError(HTTPStatus.BAD_GATEWAY, "Firefox did not return canvas evidence")
    return {
        "schema": "patternkit.agent.visual/v1",
        "revision": int(studio.get("revision") or 0),
        "mime_type": "image/png",
        "scope": "canvas-only",
        "image_base64": encoded,
    }


def _event_payload(event: dict[str, Any], started: dict[str, float]) -> dict[str, object] | None:
    method = str(event.get("method") or "")
    params = event.get("params") if isinstance(event.get("params"), dict) else {}
    if method == "log.entryAdded":
        entry = params.get("entry") if isinstance(params.get("entry"), dict) else params
        return {
            "type": method,
            "level": entry.get("level"),
            "message": entry.get("text"),
            "url": entry.get("source", {}).get("url") if isinstance(entry.get("source"), dict) else "",
        }
    if method in {"network.responseCompleted", "network.fetchError"}:
        request = params.get("request") if isinstance(params.get("request"), dict) else {}
        response = params.get("response") if isinstance(params.get("response"), dict) else {}
        request_id = str(request.get("request") or params.get("requestId") or "")
        timestamp = float(params.get("timestamp") or time.monotonic())
        start = started.pop(request_id, timestamp)
        return {
            "type": method,
            "url": response.get("url") or request.get("url") or "",
            "status": response.get("status") or 0,
            "duration_ms": max(0, int((timestamp - start) * 1000)),
            "failed": method == "network.fetchError",
        }
    if method == "network.beforeRequestSent":
        request = params.get("request") if isinstance(params.get("request"), dict) else {}
        request_id = str(request.get("request") or params.get("requestId") or "")
        started[request_id] = float(params.get("timestamp") or time.monotonic())
    return None


def _agent_diagnostics(session: str, observe_seconds: float, slow_ms: int) -> dict[str, object]:
    binding = _require_exact_binding(session=session)
    _studio_request("GET", _studio_api_path("session", session))
    diagnostic = _studio_request("GET", _studio_api_path("diagnostics", session))
    events: list[dict[str, object]] = []
    started: dict[str, float] = {}
    if observe_seconds > 0:
        with _Bidi() as bidi:
            context = _studio_bidi_context(bidi, binding)
            bidi.call(
                "session.subscribe",
                {"events": ["log.entryAdded", "network.beforeRequestSent", "network.responseCompleted", "network.fetchError"], "contexts": [context["id"]]},
            )
            deadline = time.monotonic() + observe_seconds
            while time.monotonic() < deadline and len(events) < 100:
                event = bidi.event(deadline - time.monotonic())
                if event is None:
                    break
                payload = _event_payload(event, started)
                if payload:
                    sanitized = _sanitize_browser_event(payload, slow_ms=slow_ms)
                    if sanitized["failed"] or sanitized["slow"] or sanitized["type"] == "log.entryAdded":
                        events.append(sanitized)
    return {
        "schema": "patternkit.agent.diagnostics/v1",
        "ok": True,
        "binding": _public_binding(binding),
        "app_session_render": _sanitize_app_diagnostic(diagnostic),
        "browser_events": events,
        "observation_seconds": observe_seconds,
        "slow_threshold_ms": slow_ms,
    }


def _synthetic_contract() -> dict[str, object]:
    state: dict[str, object] = {
        "binding_id": "synthetic-binding",
        "browser_start_identity": "100:200",
        "target_id": "tab-A",
        "session": "atelier",
    }
    expected_url = f"{TARGET_ORIGIN}/?session=atelier&pk-share=synthetic-binding"

    def valid(url: str, *, process: str = "100:200", target_id: str = "tab-A") -> bool:
        return _binding_matches(state, process, {"id": target_id, "url": url})[0]

    cases = {
        "exact_active_tab": valid(expected_url),
        "browser_restart_fails_closed": not valid(expected_url, process="300:400"),
        "tab_switch_fails_closed": not valid(expected_url, target_id="tab-B"),
        "copied_url_fails_closed": not valid(expected_url, target_id="replacement-tab"),
        "stale_nonce_fails_closed": not valid(f"{TARGET_ORIGIN}/?pk-share=stale"),
        "duplicate_nonce_fails_closed": not valid(f"{expected_url}&pk-share=duplicate"),
        "wrong_origin_fails_closed": not valid("https://browser.eyrie/?pk-share=synthetic-binding"),
    }
    return {"schema": "patternkit.workbench.synthetic-contract/v1", "ok": all(cases.values()), "cases": cases}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"workbench-bridge {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else '-'}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value: dict[str, object], status: int = HTTPStatus.OK) -> None:
        self._send(status, (json.dumps(value, sort_keys=True) + "\n").encode(), "application/json")

    def _bridge_authorized(self) -> bool:
        supplied = self.headers.get("X-PatternKit-Bridge-Token", "")
        return bool(BRIDGE_TOKEN and supplied and secrets.compare_digest(supplied, BRIDGE_TOKEN))

    def _agent_authorized(self, *, send_error: bool = True) -> bool:
        supplied = self.headers.get("X-PatternKit-Agent-Token", "")
        if AGENT_TOKEN and supplied and secrets.compare_digest(supplied, AGENT_TOKEN):
            return True
        if send_error:
            self._send(HTTPStatus.FORBIDDEN, b"forbidden\n", "text/plain")
        return False

    def _agent_error(self, exc: AgentRequestError) -> None:
        self._json({"schema": "patternkit.agent.error/v1", "ok": False, "error": str(exc)}, exc.status)

    def do_GET(self) -> None:
        parsed_request = urlsplit(self.path)
        path = parsed_request.path
        query = parse_qs(parsed_request.query, keep_blank_values=True)
        if path == "/health":
            self._send(HTTPStatus.OK, b"ok\n", "text/plain")
            return
        if path.startswith("/agent/"):
            if not self._agent_authorized():
                return
            try:
                session = _session_name((query.get("session") or ["atelier"])[0])
                if path == "/agent/status":
                    self._json(_agent_status(session))
                elif path == "/agent/runtime-canary":
                    self._json(_agent_runtime_canary())
                elif path == "/agent/snapshot":
                    self._json(_agent_snapshot(session))
                elif path == "/agent/visual":
                    self._json(_agent_visual(session))
                elif path == "/agent/diagnostics":
                    observe = min(5.0, max(0.0, float((query.get("observe_seconds") or ["1"])[0])))
                    slow_ms = min(10000, max(100, int((query.get("slow_ms") or ["1000"])[0])))
                    self._json(_agent_diagnostics(session, observe, slow_ms))
                else:
                    self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")
            except (AgentRequestError, ValueError) as exc:
                error = exc if isinstance(exc, AgentRequestError) else AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid agent request")
                self._agent_error(error)
            return
        if path == "/status":
            if not _is_loopback(self.client_address[0]) and not self._bridge_authorized():
                self._send(HTTPStatus.FORBIDDEN, b"forbidden\n", "text/plain")
                return
            self._json(_public_binding(_validated_state()))
            return
        if path == "/synthetic-contract":
            if not self._bridge_authorized():
                self._send(HTTPStatus.FORBIDDEN, b"forbidden\n", "text/plain")
                return
            contract = _synthetic_contract()
            self._json(contract, HTTPStatus.OK if contract["ok"] else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/share":
            if not _is_loopback(self.client_address[0]):
                self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")
                return
            process = _browser_start_identity()
            active_context = _active_context(require_isolated=False)
            active_url = urlsplit(active_context.get("url", "")) if active_context else None
            if process is None or active_context is None or active_url is None or active_url.scheme != "http" or active_url.hostname != "127.0.0.1" or active_url.port != PORT:
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"Firefox is not ready\n", "text/plain")
                return
            binding = secrets.token_urlsafe(18)
            target = f"{TARGET_ORIGIN}/?{urlencode({'session': 'atelier', 'pk-share': binding})}"
            _write_state({
                "schema": "patternkit.workbench.binding-state/v1",
                "binding_id": binding,
                "browser_start_identity": process,
                "target_id": active_context["id"],
                "session": "atelier",
                "bound_at": time.time(),
            })
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", target)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/":
            if not _is_loopback(self.client_address[0]):
                self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")
                return
            body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Pattern Kit workbench</title>
<style>body{{font:18px system-ui;margin:4rem;max-width:48rem;background:#17151d;color:#eee8f5}}a{{display:inline-block;padding:.8rem 1.1rem;border-radius:.6rem;background:#8f6bd1;color:white;text-decoration:none}}code{{color:#cfb8ff}}</style></head>
<body><h1>Pattern Kit workbench</h1><p>This Firefox profile is isolated from <code>browser.eyrie</code>. Choose the visible action below to bind the exact tab for Star. The binding is checked against the active URL and this Firefox process generation on every reconnect.</p><p><a href="/share">Open and share Pattern Kit Studio</a></p></body></html>""".encode()
            self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")
            return
        self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in {"/agent/control", "/agent/input"} or not self._agent_authorized():
            if path not in {"/agent/control", "/agent/input"}:
                self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid agent request body")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid agent request document")
            session = _session_name(payload.get("session"))
            binding = _require_exact_binding(session=session)
            if path == "/agent/control":
                self._json(_execute_agent_control(payload))
                return
            self._json(_execute_agent_input(binding, payload))
        except (AgentRequestError, ValueError, TypeError, json.JSONDecodeError) as exc:
            error = exc if isinstance(exc, AgentRequestError) else AgentRequestError(HTTPStatus.BAD_REQUEST, "invalid agent request")
            self._agent_error(error)

    do_HEAD = do_GET


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
