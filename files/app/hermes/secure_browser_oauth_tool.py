"""Safe shared secure-browser OAuth bridge for Talon.

This custom Hermes toolset gives Talon bounded control of a Puppet/KubeCM
managed persistent Kasm browser for owner-operated OAuth/device-code flows.  It
intentionally exposes only navigation, high-level status, and redacted current
page metadata.  Joy performs Bitwarden unlock, account login, passkeys, 2FA,
CAPTCHA, and consent prompts through the authenticated Kasm UI.

The bridge must never return cookies, storage, raw HTML, request headers,
Chrome DevTools endpoints, screenshots of secret pages, callback URLs containing
codes, vault contents, credentials, or token material.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import urlopen

import websockets.sync.client
from tools.registry import registry

TOOLSET = "secure_browser"
NAMESPACE = os.environ.get("SECURE_BROWSER_NAMESPACE", os.environ.get("SECURE_BROWSER_OAUTH_NAMESPACE", "ai"))
WORKLOAD = os.environ.get("SECURE_BROWSER_WORKLOAD", os.environ.get("SECURE_BROWSER_OAUTH_WORKLOAD", "deployment/secure-browser"))
REMOTE_DEBUG_PORT = int(os.environ.get("SECURE_BROWSER_CDP_PORT", os.environ.get("SECURE_BROWSER_OAUTH_CDP_PORT", "9222")))
PUBLIC_URL = os.environ.get("SECURE_BROWSER_PUBLIC_URL", os.environ.get("SECURE_BROWSER_OAUTH_PUBLIC_URL", "https://secure-browser.eyrie/"))
BROWSER_OWNER = os.environ.get("SECURE_BROWSER_OWNER", os.environ.get("SECURE_BROWSER_OAUTH_OWNER", "oauth"))
OWNERSHIP_STATE_PATH = os.environ.get("SECURE_BROWSER_OWNERSHIP_STATE", os.path.expanduser("~/.hermes/secure-browser-tabs.json"))
AUDIT_LOG = os.environ.get("SECURE_BROWSER_AUDIT_LOG", os.environ.get("SECURE_BROWSER_OAUTH_AUDIT_LOG", os.path.expanduser("~/.hermes/profiles/talon/secure-browser-oauth-audit.log")))
MAX_RESULT_CHARS = 12000
MAX_TITLE_CHARS = 180
PORT_FORWARD_TIMEOUT_SECONDS = 20
PAGE_LOAD_TIMEOUT_SECONDS = 20
CDP_MAX_MESSAGE_BYTES = 8 * 1024 * 1024

SENSITIVE_QUERY_KEYS = re.compile(r"(?:^|_)(code|token|id_token|access_token|refresh_token|secret|password|passkey|otp|state|session|ticket)(?:_|$)", re.IGNORECASE)
SENSITIVE_URL_TEXT = re.compile(r"(access_token|refresh_token|id_token|code=|password|passkey|otp|verification|captcha)", re.IGNORECASE)
SENSITIVE_TITLE_TEXT = re.compile(r"(password|passkey|one-time|verification code|captcha|security check|2fa|two-factor)", re.IGNORECASE)
MUTATING_JS_TOKENS = re.compile(r"\b(click|submit|fetch|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|indexedDB|cookie|setAttribute|removeAttribute|appendChild|removeChild|innerHTML\s*=|location\s*=|open\s*\()\b", re.IGNORECASE)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _check_secure_browser_oauth() -> bool:
    return shutil.which("kubectl") is not None


def _audit(action: str, payload: dict[str, Any]) -> None:
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "toolset": TOOLSET,
            "action": action,
            "payload": payload,
        }
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Audit is defense-in-depth; tool calls should still report their action.
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _redact_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return "[non-url redacted]"
    if SENSITIVE_URL_TEXT.search(raw):
        query = []
        for key, val in parse_qsl(parsed.query, keep_blank_values=True):
            if SENSITIVE_QUERY_KEYS.search(key):
                query.append((key, "[redacted]"))
            else:
                query.append((key, val[:80]))
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query), "[redacted]" if parsed.fragment else ""))
    # OAuth URLs can have very long non-secret request metadata.  Return origin
    # and path plus compact query keys so the agent can identify the page without
    # carrying full callback material in context/logs.
    if parsed.query:
        keys = [key for key, _val in parse_qsl(parsed.query, keep_blank_values=True)[:12]]
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "&".join(f"{key}=…" for key in keys), ""))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _safe_navigation_url(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Secure-browser OAuth navigation only accepts http(s) URLs")
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Secure-browser OAuth navigation requires https except localhost")
    return candidate


def _safe_title(value: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    if not title:
        return ""
    if SENSITIVE_TITLE_TEXT.search(title):
        return "[sensitive login/challenge title redacted]"
    return title[:MAX_TITLE_CHARS]


class PortForward:
    def __init__(self) -> None:
        self.local_port = _free_port()
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> int:
        cmd = [
            "kubectl",
            "-n",
            NAMESPACE,
            "port-forward",
            "--address",
            "127.0.0.1",
            WORKLOAD,
            f"{self.local_port}:{REMOTE_DEBUG_PORT}",
        ]
        env = os.environ.copy()
        env.setdefault("HOME", "/home/joy")
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        deadline = time.time() + PORT_FORWARD_TIMEOUT_SECONDS
        version_url = f"http://127.0.0.1:{self.local_port}/json/version"
        while time.time() < deadline:
            if self.process.poll() is not None:
                stderr = (self.process.stderr.read() if self.process.stderr else "").strip()
                raise RuntimeError(f"kubectl port-forward failed: {stderr[:500]}")
            try:
                with urlopen(version_url, timeout=1) as response:
                    json.loads(response.read().decode("utf-8"))
                return self.local_port
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("timed out waiting for Secure-browser OAuth CDP bridge")

    def __exit__(self, *_exc: object) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


class CdpSession:
    def __init__(self, websocket_url: str, port: int | None = None) -> None:
        self.ws = websockets.sync.client.connect(websocket_url, open_timeout=5, close_timeout=2, max_size=CDP_MAX_MESSAGE_BYTES)
        self.next_id = 1
        self.port = port

    def close(self) -> None:
        self.ws.close()

    def call(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"id": self.next_id, "method": method}
        call_id = self.next_id
        self.next_id += 1
        if params is not None:
            msg["params"] = params
        if session_id is not None:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        while True:
            data = json.loads(self.ws.recv(timeout=10))
            if data.get("id") == call_id:
                if "error" in data:
                    raise RuntimeError(f"CDP {method} failed: {data['error'].get('message', 'unknown error')}")
                return data.get("result") or {}


def _browser_ws_url(port: int) -> str:
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
        version = json.loads(response.read().decode("utf-8"))
    url = str(version.get("webSocketDebuggerUrl") or "")
    if not url:
        raise RuntimeError("Secure-browser OAuth CDP endpoint did not report a browser websocket")
    return url


def _page_targets_from_http(port: int) -> list[dict[str, Any]]:
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [item for item in data if item.get("type") == "page"]


def _current_page_ids(browser: CdpSession) -> set[str]:
    ids: set[str] = set()
    if browser.port is not None:
        with contextlib.suppress(Exception):
            ids.update(str(target["id"]) for target in _page_targets_from_http(browser.port) if target.get("id"))
    with contextlib.suppress(Exception):
        targets = browser.call("Target.getTargets").get("targetInfos") or []
        ids.update(str(target["targetId"]) for target in targets if target.get("type") == "page" and target.get("targetId"))
    return ids


def _load_owner_state(handle: Any) -> dict[str, Any]:
    handle.seek(0)
    raw = handle.read()
    if not raw.strip():
        return {"owners": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"owners": {}}
    if not isinstance(data, dict):
        return {"owners": {}}
    owners = data.get("owners")
    if not isinstance(owners, dict):
        data["owners"] = {}
    return data


def _store_owner_state(handle: Any, state: dict[str, Any]) -> None:
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def _claim_owner_target(browser: CdpSession, create: bool = False) -> str:
    os.makedirs(os.path.dirname(OWNERSHIP_STATE_PATH) or ".", exist_ok=True)
    with open(OWNERSHIP_STATE_PATH, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            state = _load_owner_state(handle)
            owners = state.setdefault("owners", {})
            live_ids = _current_page_ids(browser)
            existing = str(owners.get(BROWSER_OWNER, {}).get("target_id") or "")
            if existing and existing in live_ids and not create:
                return existing
            target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
            owners[BROWSER_OWNER] = {
                "target_id": target_id,
                "toolset": TOOLSET,
                "workload": WORKLOAD,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _store_owner_state(handle, state)
            return target_id
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _first_page_target(browser: CdpSession) -> str:
    return _claim_owner_target(browser, create=False)


def _attach(browser: CdpSession, target_id: str) -> str:
    result = browser.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    session_id = str(result["sessionId"])
    browser.call("Runtime.enable", session_id=session_id)
    browser.call("Page.enable", session_id=session_id)
    return session_id


def _evaluate(browser: CdpSession, session_id: str, expression: str) -> Any:
    result = browser.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, session_id=session_id)
    value = result.get("result") or {}
    return value.get("value")


def _with_browser(fn: Any) -> dict[str, Any]:
    with PortForward() as port:
        browser = CdpSession(_browser_ws_url(port), port=port)
        try:
            return fn(browser)
        finally:
            browser.close()


def _page_summary(browser: CdpSession, session_id: str) -> dict[str, Any]:
    href = str(_evaluate(browser, session_id, "location.href") or "")
    title = str(_evaluate(browser, session_id, "document.title") or "")
    parsed = urlparse(href)
    return {
        "url": _redact_url(href),
        "origin": f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "",
        "path": parsed.path[:160],
        "query_keys": [key for key, _value in parse_qsl(parsed.query, keep_blank_values=True)[:20]],
        "has_fragment": bool(parsed.fragment),
        "page_title": _safe_title(title),
        "sensitive_title_redacted": _safe_title(title) != re.sub(r"\s+", " ", title).strip()[:MAX_TITLE_CHARS],
    }


def _navigate(url: str, new_page: bool = False) -> dict[str, Any]:
    safe_url = _safe_navigation_url(url)

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _claim_owner_target(browser, create=True) if new_page else _first_page_target(browser)
        session_id = _attach(browser, target_id)
        browser.call("Page.navigate", {"url": safe_url}, session_id=session_id)
        deadline = time.time() + PAGE_LOAD_TIMEOUT_SECONDS
        while time.time() < deadline:
            ready = _evaluate(browser, session_id, "document.readyState")
            if ready in ("interactive", "complete"):
                time.sleep(0.8)
                break
            time.sleep(0.25)
        summary = _page_summary(browser, session_id)
        result = {"operation": "navigate", "status": "ok", "public_browser_url": PUBLIC_URL, "secure_browser_owner": BROWSER_OWNER, **summary}
        _audit("navigate", {"url": result["url"], "origin": result["origin"], "path": result["path"], "new_page": new_page})
        return result

    return _with_browser(run)


def _current_page_summary() -> dict[str, Any]:
    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        summary = _page_summary(browser, session_id)
        summary.update({
            "operation": "current_page_summary",
            "public_browser_url": PUBLIC_URL,
            "secure_browser_owner": BROWSER_OWNER,
            "policy": "Redacted page metadata only. Joy handles login/2FA/CAPTCHA/consent in the Kasm UI; Talon must not request or expose token values, callback codes, cookies, storage, raw DOM, screenshots of secret pages, or credentials.",
        })
        return summary

    return _with_browser(run)


def _readiness_status() -> dict[str, Any]:
    base = {
        "toolset": TOOLSET,
        "namespace": NAMESPACE,
        "workload": WORKLOAD,
        "remote_debug_port": REMOTE_DEBUG_PORT,
        "secure_browser_owner": BROWSER_OWNER,
        "ownership_state_path": OWNERSHIP_STATE_PATH,
        "public_browser_url": PUBLIC_URL,
        "available": _check_secure_browser_oauth(),
        "boundary": "Secure-browser OAuth tools provide navigation and redacted page metadata only; Joy performs credential entry and approvals through Kasm.",
    }
    if not base["available"]:
        return base
    cmd = ["kubectl", "-n", NAMESPACE, "get", WORKLOAD, "-o", "json"]
    env = os.environ.copy()
    env.setdefault("HOME", "/home/joy")
    try:
        proc = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=10, env=env)
        base["kubectl_exit_code"] = proc.returncode
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            base["ready_replicas"] = data.get("status", {}).get("readyReplicas", 0)
            base["replicas"] = data.get("status", {}).get("replicas", 0)
            base["observed_generation"] = data.get("status", {}).get("observedGeneration")
        else:
            base["kubectl_error"] = proc.stderr[-500:]
    except Exception as err:
        base["kubectl_error"] = str(err)[:500]
    return base


def secure_browser_oauth_status_tool(args: dict[str, Any], **_kw: Any) -> str:
    status = _readiness_status()
    if bool(args.get("include_page", True)) and status.get("available"):
        try:
            status["page"] = _current_page_summary()
        except Exception as err:
            status["page_error"] = str(err)[:500]
    return _json(status)


def secure_browser_oauth_navigate_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_navigate(str(args.get("url") or ""), bool(args.get("new_page", False))))
    except Exception as err:
        return _json({"operation": "navigate", "status": "error", "error": str(err)[:800], "public_browser_url": PUBLIC_URL})


def secure_browser_oauth_current_page_summary_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_current_page_summary())
    except Exception as err:
        return _json({"operation": "current_page_summary", "status": "error", "error": str(err)[:800], "public_browser_url": PUBLIC_URL})


def secure_browser_oauth_read_only_query_tool(args: dict[str, Any], **_kw: Any) -> str:
    expression = str(args.get("expression") or "").strip()
    if not expression:
        return _json({"operation": "read_only_query", "status": "error", "error": "expression is required"})
    if len(expression) > 1000 or MUTATING_JS_TOKENS.search(expression):
        return _json({"operation": "read_only_query", "status": "error", "error": "expression is too long or contains mutating/network/storage/navigation tokens"})

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        page = _page_summary(browser, session_id)
        value = _evaluate(browser, session_id, f"(() => {{ const value = ({expression}); return value; }})()")
        safe_value = json.loads(json.dumps(value, ensure_ascii=False, default=str))
        rendered = json.dumps(safe_value, ensure_ascii=False, sort_keys=True, default=str)
        if SENSITIVE_URL_TEXT.search(rendered) or len(rendered) > 4000:
            rendered = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            return {"operation": "read_only_query", "status": "redacted", "page": page, "value_sha256": rendered, "redaction_reason": "query result looked sensitive or too large"}
        return {"operation": "read_only_query", "status": "ok", "page": page, "value": safe_value}

    try:
        return _json(_with_browser(run))
    except Exception as err:
        return _json({"operation": "read_only_query", "status": "error", "error": str(err)[:800]})


def secure_browser_oauth_login_prompt_tool(args: dict[str, Any], **_kw: Any) -> str:
    flow_label = re.sub(r"\s+", " ", str(args.get("flow_label") or "OpenAI Codex OAuth")).strip()[:120]
    url = str(args.get("url") or "").strip()
    navigate_result: dict[str, Any] | None = None
    if url:
        try:
            navigate_result = _navigate(url, False)
        except Exception as err:
            navigate_result = {"operation": "navigate", "status": "error", "error": str(err)[:800]}
    prompt = (
        f"Please open {PUBLIC_URL} and use the {BROWSER_OWNER} tab/session to complete the {flow_label} login/consent flow in the shared secure browser. "
        "Use Bitwarden/passkeys/2FA/CAPTCHA directly in the browser UI. Do not paste codes, tokens, callback URLs, cookies, or credentials into chat. "
        "When the browser shows the OAuth flow is complete, tell Talon only which label to capture next (primary or secondary)."
    )
    result = {"operation": "login_prompt", "status": "ready", "public_browser_url": PUBLIC_URL, "secure_browser_owner": BROWSER_OWNER, "prompt_for_joy": prompt, "navigation": navigate_result}
    _audit("login_prompt", {"flow_label": flow_label, "navigated": bool(url), "navigation_status": (navigate_result or {}).get("status")})
    return _json(result)


DEVICE_CODE_STATE_PATH = os.environ.get("SECURE_BROWSER_DEVICE_CODE_STATE", os.path.expanduser("~/.hermes/secure-browser-device-codes.json"))
DEVICE_CODE_VISIBLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{3,80}$")


def _device_flow_state() -> dict[str, Any]:
    try:
        with open(DEVICE_CODE_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _store_device_flow_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DEVICE_CODE_STATE_PATH) or ".", exist_ok=True)
    with open(DEVICE_CODE_STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _safe_device_code(value: str) -> str:
    code = re.sub(r"\s+", " ", str(value or "")).strip()
    if not code or not DEVICE_CODE_VISIBLE_RE.match(code) or SENSITIVE_URL_TEXT.search(code):
        raise ValueError("device code must be the short provider-visible user code, not a token, URL, password, callback, or credential")
    return code[:80]


def secure_browser_device_code_prompt_tool(args: dict[str, Any], **_kw: Any) -> str:
    flow_label = re.sub(r"\s+", " ", str(args.get("flow_label") or "OAuth device flow")).strip()[:120]
    user_code = _safe_device_code(str(args.get("user_code") or ""))
    verification_url = _safe_navigation_url(str(args.get("verification_url") or ""))
    expires_in = int(args.get("expires_in_seconds") or 0)
    interval = int(args.get("poll_interval_seconds") or 5)
    navigate = bool(args.get("navigate", True))
    navigation: dict[str, Any] | None = None
    if navigate:
        try:
            navigation = _navigate(verification_url, False)
        except Exception as err:
            navigation = {"operation": "navigate", "status": "error", "error": str(err)[:800]}
    started_at = datetime.now(timezone.utc).isoformat()
    expires_at = None
    if expires_in > 0:
        expires_at = datetime.fromtimestamp(time.time() + expires_in, timezone.utc).isoformat()
    state = _device_flow_state()
    state[flow_label] = {"flow_label": flow_label, "verification_url": _redact_url(verification_url), "user_code": user_code, "started_at": started_at, "expires_at": expires_at, "poll_interval_seconds": max(1, min(interval, 60)), "status": "waiting_for_owner"}
    _store_device_flow_state(state)
    prompt = (
        f"Please open {PUBLIC_URL} and use the {BROWSER_OWNER} tab/session to complete {flow_label}. "
        f"Go to {verification_url} and enter device code: {user_code}. "
        "Use Bitwarden/passkeys/2FA/CAPTCHA directly in the browser UI if the provider asks. "
        "Do not paste tokens, callback URLs, cookies, passwords, or credential material into chat."
    )
    _audit("device_code_prompt", {"flow_label": flow_label, "verification_url": _redact_url(verification_url), "navigated": navigate, "navigation_status": (navigation or {}).get("status")})
    return _json({"operation": "device_code_prompt", "status": "waiting_for_owner", "flow_label": flow_label, "user_code": user_code, "verification_url": _redact_url(verification_url), "public_browser_url": PUBLIC_URL, "secure_browser_owner": BROWSER_OWNER, "expires_at": expires_at, "poll_interval_seconds": max(1, min(interval, 60)), "prompt_for_joy": prompt, "navigation": navigation})


def secure_browser_oauth_wait_for_completion_tool(args: dict[str, Any], **_kw: Any) -> str:
    flow_label = re.sub(r"\s+", " ", str(args.get("flow_label") or "OAuth/device flow")).strip()[:120]
    success_title_pattern = str(args.get("success_title_pattern") or "success|complete|authorized|authentication complete|you may close")
    timeout_seconds = max(1, min(int(args.get("timeout_seconds") or 60), 600))
    compiled = re.compile(success_title_pattern, re.IGNORECASE)
    deadline = time.time() + timeout_seconds
    last_summary: dict[str, Any] | None = None
    status = "timeout"
    while time.time() < deadline:
        try:
            last_summary = _current_page_summary()
            title = str(last_summary.get("page_title") or "")
            path = str(last_summary.get("path") or "")
            if compiled.search(title) or compiled.search(path):
                status = "completed"
                break
        except Exception as err:
            last_summary = {"operation": "wait_for_completion", "status": "error", "error": str(err)[:500]}
        time.sleep(min(5, max(1, int(args.get("poll_interval_seconds") or 3))))
    state = _device_flow_state()
    if flow_label in state:
        state[flow_label]["status"] = status
        state[flow_label]["last_checked_at"] = datetime.now(timezone.utc).isoformat()
        _store_device_flow_state(state)
    return _json({"operation": "wait_for_completion", "status": status, "flow_label": flow_label, "page": last_summary, "boundary": "Returns only sanitized page metadata and a completion/timeout status; it does not read tokens, cookies, callback codes, raw DOM, storage, or credentials."})


STATUS_SCHEMA = {
    "name": "secure_browser_oauth_status",
    "description": "Show secure-browser OAuth bridge/workload status and optionally redacted current-page metadata. Does not return tokens, cookies, storage, raw HTML, screenshots, CDP endpoints, callback codes, credentials, or vault contents.",
    "parameters": {"type": "object", "properties": {"include_page": {"type": "boolean", "default": True}}, "additionalProperties": False},
}
NAVIGATE_SCHEMA = {
    "name": "secure_browser_oauth_navigate",
    "description": "Navigate the persistent shared secure-browser OAuth to an HTTPS URL for Joy-operated login/consent. Returns only redacted page metadata; callback codes/fragments are redacted.",
    "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "new_page": {"type": "boolean", "default": False}}, "required": ["url"], "additionalProperties": False},
}
SUMMARY_SCHEMA = {
    "name": "secure_browser_oauth_current_page_summary",
    "description": "Read sanitized current-page metadata from the Secure-browser OAuth: origin/path/title/query-key names only. No visible text, raw DOM, cookies, storage, screenshots, callback codes, or credentials are returned.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
QUERY_SCHEMA = {
    "name": "secure_browser_oauth_read_only_query",
    "description": "Evaluate a tightly limited read-only JavaScript expression for non-secret facts. Mutating/network/storage/navigation tokens are blocked and sensitive-looking results are hashed/redacted.",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False},
}
PROMPT_SCHEMA = {
    "name": "secure_browser_oauth_login_prompt",
    "description": "Prepare an owner-facing prompt for Joy to complete an OAuth login/consent flow in the shared browser, optionally navigating there first. The prompt explicitly forbids sharing codes/tokens/credentials in chat.",
    "parameters": {"type": "object", "properties": {"flow_label": {"type": "string"}, "url": {"type": "string"}}, "additionalProperties": False},
}


DEVICE_CODE_PROMPT_SCHEMA = {
    "name": "secure_browser_device_code_prompt",
    "description": "Open or prepare a provider device-code verification page in the shared secure browser, show Joy the short user code, and track only sanitized flow state. Never pass tokens, client secrets, callback URLs, credentials, cookies, storage, raw DOM, or 2FA/CAPTCHA data.",
    "parameters": {"type": "object", "properties": {"flow_label": {"type": "string"}, "verification_url": {"type": "string"}, "user_code": {"type": "string"}, "expires_in_seconds": {"type": "integer", "default": 0}, "poll_interval_seconds": {"type": "integer", "default": 5}, "navigate": {"type": "boolean", "default": True}}, "required": ["verification_url", "user_code"], "additionalProperties": False},
}
WAIT_FOR_COMPLETION_SCHEMA = {
    "name": "secure_browser_oauth_wait_for_completion",
    "description": "Poll the secure browser page for a sanitized OAuth/device-flow completion signal by title/path pattern. Returns completion/timeout and redacted page metadata only; does not expose tokens, callback codes, cookies, storage, raw DOM, screenshots, or credentials.",
    "parameters": {"type": "object", "properties": {"flow_label": {"type": "string"}, "success_title_pattern": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 60}, "poll_interval_seconds": {"type": "integer", "default": 3}}, "additionalProperties": False},
}

for schema, handler, emoji in (
    (STATUS_SCHEMA, secure_browser_oauth_status_tool, "🔐"),
    (NAVIGATE_SCHEMA, secure_browser_oauth_navigate_tool, "🧭"),
    (SUMMARY_SCHEMA, secure_browser_oauth_current_page_summary_tool, "📄"),
    (QUERY_SCHEMA, secure_browser_oauth_read_only_query_tool, "🔎"),
    (PROMPT_SCHEMA, secure_browser_oauth_login_prompt_tool, "🙋"),
    (DEVICE_CODE_PROMPT_SCHEMA, secure_browser_device_code_prompt_tool, "🔢"),
    (WAIT_FOR_COMPLETION_SCHEMA, secure_browser_oauth_wait_for_completion_tool, "✅"),
):
    registry.register(
        name=schema["name"],
        toolset=TOOLSET,
        schema=schema,
        handler=handler,
        check_fn=_check_secure_browser_oauth,
        description=schema["description"],
        emoji=emoji,
        max_result_size_chars=MAX_RESULT_CHARS,
    )
