#!/usr/bin/env python3
"""Visible, fail-closed active-tab binding for the Pattern Kit workbench."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

HOST = os.environ.get("PATTERNKIT_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("PATTERNKIT_BRIDGE_PORT", "8766"))
TARGET_ORIGIN = os.environ.get("PATTERNKIT_ORIGIN", "https://patternkit.eyrie").rstrip("/")
STATE_PATH = Path(os.environ.get("PATTERNKIT_BINDING_STATE", "/home/kasm-user/.patternkit-workbench/binding.json"))
DISPLAY = os.environ.get("DISPLAY", ":1")
NODE_NAME = os.environ.get("PATTERNKIT_NODE_NAME", "")
BRIDGE_TOKEN = os.environ.get("PATTERNKIT_BRIDGE_TOKEN", "")


def _is_loopback(address: str) -> bool:
    return address in {"127.0.0.1", "::1"}


def _browser_start_identity() -> str | None:
    try:
        output = subprocess.check_output(["pgrep", "-o", "firefox"], text=True, timeout=2).strip()
        fields = Path(f"/proc/{int(output)}/stat").read_text().split()
        return f"{output}:{fields[21]}"
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _active_context() -> dict[str, str] | None:
    env = {**os.environ, "DISPLAY": DISPLAY}
    try:
        window = subprocess.check_output(["xdotool", "getactivewindow"], env=env, text=True, timeout=3).strip()
        window_class = subprocess.check_output(["xdotool", "getwindowclassname", window], env=env, text=True, timeout=3).strip().lower()
        if "firefox" not in window_class:
            return None
        active_title = subprocess.check_output(["xdotool", "getwindowname", window], env=env, text=True, timeout=3).strip()
        with urlopen("http://127.0.0.1:9222/json/list", timeout=3) as response:
            contexts = json.loads(response.read())
        if not isinstance(contexts, list):
            return None
        browser_title = active_title
        for suffix in (" — Mozilla Firefox", " - Mozilla Firefox"):
            if browser_title.endswith(suffix):
                browser_title = browser_title[:-len(suffix)]
                break
        matches = [item for item in contexts if item.get("type") == "page" and item.get("title") == browser_title]
        if len(matches) != 1:
            return None
        value = str(matches[0].get("url", ""))
        target_id = str(matches[0].get("id", "")).strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not target_id:
            return None
        return {"id": target_id, "url": value}
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError, IndexError):
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
    active_origin_matches = bool(
        parsed_active
        and parsed_active.scheme == parsed_target.scheme
        and parsed_active.netloc == parsed_target.netloc
    )
    active_bindings = parse_qs(parsed_active.query).get("pk-share", []) if parsed_active else []
    valid = bool(
        state
        and process
        and state.get("target_id")
        and state.get("browser_start_identity") == process
        and active_origin_matches
        and len(active_bindings) == 1
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
        "reason": "verified-active-tab" if valid else "explicit-share-required",
    }


def _synthetic_contract() -> dict[str, object]:
    state: dict[str, object] = {
        "binding_id": "synthetic-binding",
        "browser_start_identity": "100:200",
        "target_id": "tab-A",
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
    return {
        "schema": "patternkit.workbench.synthetic-contract/v1",
        "ok": all(cases.values()),
        "cases": cases,
    }


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

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._send(HTTPStatus.OK, b"ok\n", "text/plain")
            return
        if path == "/status":
            if not _is_loopback(self.client_address[0]) and not self._bridge_authorized():
                self._send(HTTPStatus.FORBIDDEN, b"forbidden\n", "text/plain")
                return
            self._json(_validated_state())
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
            active_context = _active_context()
            active_url = urlsplit(active_context.get("url", "")) if active_context else None
            if (
                process is None
                or active_context is None
                or active_url is None
                or active_url.scheme != "http"
                or active_url.hostname != "127.0.0.1"
                or active_url.port != PORT
            ):
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"Firefox is not ready\n", "text/plain")
                return
            binding = secrets.token_urlsafe(18)
            target = f"{TARGET_ORIGIN}/?{urlencode({'session': 'atelier', 'pk-share': binding})}"
            _write_state({
                "schema": "patternkit.workbench.binding-state/v1",
                "binding_id": binding,
                "browser_start_identity": process,
                "target_id": active_context["id"],
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

    do_HEAD = do_GET


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
