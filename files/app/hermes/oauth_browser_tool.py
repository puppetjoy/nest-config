"""Safe shared OAuth browser bridge for Talon.

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

TOOLSET = "oauth_browser"
NAMESPACE = os.environ.get("OAUTH_BROWSER_NAMESPACE", "ai")
WORKLOAD = os.environ.get("OAUTH_BROWSER_WORKLOAD", "deployment/oauth-browser")
REMOTE_DEBUG_PORT = int(os.environ.get("OAUTH_BROWSER_CDP_PORT", "9222"))
PUBLIC_URL = os.environ.get("OAUTH_BROWSER_PUBLIC_URL", "https://oauth-browser.eyrie/")
AUDIT_LOG = os.environ.get("OAUTH_BROWSER_AUDIT_LOG", os.path.expanduser("~/.hermes/profiles/talon/oauth-browser-audit.log"))
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


def _check_oauth_browser() -> bool:
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
        raise ValueError("OAuth browser navigation only accepts http(s) URLs")
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("OAuth browser navigation requires https except localhost")
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
        raise RuntimeError("timed out waiting for OAuth browser CDP bridge")

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
        raise RuntimeError("OAuth browser CDP endpoint did not report a browser websocket")
    return url


def _page_targets_from_http(port: int) -> list[dict[str, Any]]:
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [item for item in data if item.get("type") == "page"]


def _first_page_target(browser: CdpSession) -> str:
    if browser.port is not None:
        with contextlib.suppress(Exception):
            for target in _page_targets_from_http(browser.port):
                if target.get("id"):
                    return str(target["id"])
    targets = browser.call("Target.getTargets").get("targetInfos") or []
    for target in targets:
        if target.get("type") == "page":
            return str(target["targetId"])
    return str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])


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
        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]) if new_page else _first_page_target(browser)
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
        result = {"operation": "navigate", "status": "ok", "public_browser_url": PUBLIC_URL, **summary}
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
        "public_browser_url": PUBLIC_URL,
        "available": _check_oauth_browser(),
        "boundary": "OAuth browser tools provide navigation and redacted page metadata only; Joy performs credential entry and approvals through Kasm.",
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


def oauth_browser_status_tool(args: dict[str, Any], **_kw: Any) -> str:
    status = _readiness_status()
    if bool(args.get("include_page", True)) and status.get("available"):
        try:
            status["page"] = _current_page_summary()
        except Exception as err:
            status["page_error"] = str(err)[:500]
    return _json(status)


def oauth_browser_navigate_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_navigate(str(args.get("url") or ""), bool(args.get("new_page", False))))
    except Exception as err:
        return _json({"operation": "navigate", "status": "error", "error": str(err)[:800], "public_browser_url": PUBLIC_URL})


def oauth_browser_current_page_summary_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_current_page_summary())
    except Exception as err:
        return _json({"operation": "current_page_summary", "status": "error", "error": str(err)[:800], "public_browser_url": PUBLIC_URL})


def oauth_browser_read_only_query_tool(args: dict[str, Any], **_kw: Any) -> str:
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


def oauth_browser_login_prompt_tool(args: dict[str, Any], **_kw: Any) -> str:
    flow_label = re.sub(r"\s+", " ", str(args.get("flow_label") or "OpenAI Codex OAuth")).strip()[:120]
    url = str(args.get("url") or "").strip()
    navigate_result: dict[str, Any] | None = None
    if url:
        try:
            navigate_result = _navigate(url, False)
        except Exception as err:
            navigate_result = {"operation": "navigate", "status": "error", "error": str(err)[:800]}
    prompt = (
        f"Please open {PUBLIC_URL} and complete the {flow_label} login/consent flow in the shared OAuth browser. "
        "Use Bitwarden/passkeys/2FA/CAPTCHA directly in the browser UI. Do not paste codes, tokens, callback URLs, cookies, or credentials into chat. "
        "When the browser shows the OAuth flow is complete, tell Talon only which label to capture next (primary or secondary)."
    )
    result = {"operation": "login_prompt", "status": "ready", "public_browser_url": PUBLIC_URL, "prompt_for_joy": prompt, "navigation": navigate_result}
    _audit("login_prompt", {"flow_label": flow_label, "navigated": bool(url), "navigation_status": (navigate_result or {}).get("status")})
    return _json(result)


STATUS_SCHEMA = {
    "name": "oauth_browser_status",
    "description": "Show OAuth-browser bridge/workload status and optionally redacted current-page metadata. Does not return tokens, cookies, storage, raw HTML, screenshots, CDP endpoints, callback codes, credentials, or vault contents.",
    "parameters": {"type": "object", "properties": {"include_page": {"type": "boolean", "default": True}}, "additionalProperties": False},
}
NAVIGATE_SCHEMA = {
    "name": "oauth_browser_navigate",
    "description": "Navigate the persistent shared OAuth browser to an HTTPS URL for Joy-operated login/consent. Returns only redacted page metadata; callback codes/fragments are redacted.",
    "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "new_page": {"type": "boolean", "default": False}}, "required": ["url"], "additionalProperties": False},
}
SUMMARY_SCHEMA = {
    "name": "oauth_browser_current_page_summary",
    "description": "Read sanitized current-page metadata from the OAuth browser: origin/path/title/query-key names only. No visible text, raw DOM, cookies, storage, screenshots, callback codes, or credentials are returned.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
QUERY_SCHEMA = {
    "name": "oauth_browser_read_only_query",
    "description": "Evaluate a tightly limited read-only JavaScript expression for non-secret facts. Mutating/network/storage/navigation tokens are blocked and sensitive-looking results are hashed/redacted.",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False},
}
PROMPT_SCHEMA = {
    "name": "oauth_browser_login_prompt",
    "description": "Prepare an owner-facing prompt for Joy to complete an OAuth login/consent flow in the shared browser, optionally navigating there first. The prompt explicitly forbids sharing codes/tokens/credentials in chat.",
    "parameters": {"type": "object", "properties": {"flow_label": {"type": "string"}, "url": {"type": "string"}}, "additionalProperties": False},
}

for schema, handler, emoji in (
    (STATUS_SCHEMA, oauth_browser_status_tool, "🔐"),
    (NAVIGATE_SCHEMA, oauth_browser_navigate_tool, "🧭"),
    (SUMMARY_SCHEMA, oauth_browser_current_page_summary_tool, "📄"),
    (QUERY_SCHEMA, oauth_browser_read_only_query_tool, "🔎"),
    (PROMPT_SCHEMA, oauth_browser_login_prompt_tool, "🙋"),
):
    registry.register(
        name=schema["name"],
        toolset=TOOLSET,
        schema=schema,
        handler=handler,
        check_fn=_check_oauth_browser,
        description=schema["description"],
        emoji=emoji,
        max_result_size_chars=MAX_RESULT_CHARS,
    )
