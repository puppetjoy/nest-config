"""Hermes adapter for the persistent, owner-visible Firefox desktop.

The browser uses the source-managed Firefox UI bridge inside the Kubernetes
workload. The bridge uses X11 input, AT-SPI observation, and X11 screenshots.
Opt-in v2 adds a private BiDi page connector without exposing raw profile data.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from tools.registry import registry

try:
    from hermes_constants import get_hermes_home
except ImportError:  # pragma: no cover - direct source smoke fallback
    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

TOOLSET = "secure_browser"
NAMESPACE = os.environ.get("SECURE_BROWSER_NAMESPACE", "ai")
WORKLOAD = os.environ.get("SECURE_BROWSER_WORKLOAD", "deployment/firefox")
CONTAINER = os.environ.get("SECURE_BROWSER_CONTAINER", "kasm-firefox")
BRIDGE_PATH = os.environ.get("SECURE_BROWSER_UI_BRIDGE", "/opt/nest/firefox/bin/firefox-ui-bridge.py")
CONTROL_MODE = os.environ.get("SECURE_BROWSER_CONTROL_MODE", "firefox-ui-v1")
PUBLIC_URL = os.environ.get("SECURE_BROWSER_PUBLIC_URL", "https://browser.eyrie/")
BRIDGE_TIMEOUT = int(os.environ.get("SECURE_BROWSER_UI_TIMEOUT", "60"))
MAX_RESULT_BYTES = 8_000_000
WORKFLOW_RE = re.compile(r"[^A-Za-z0-9_.:@/-]+")


def _session_env(key: str) -> str:
    try:
        from gateway.session_context import get_session_env
        return str(get_session_env(key, "") or "").strip()
    except (ImportError, RuntimeError):
        return ""


def _telegram_chat_id(value: str) -> str:
    normalized = value.removeprefix("telegram:").strip()
    return normalized.split(":", 1)[0]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _workflow_id(args: dict[str, Any], task_id: str | None = None) -> str:
    supplied = str(args.get("workflow_id") or "").strip()
    if supplied:
        return WORKFLOW_RE.sub("-", supplied)[:160]
    profile = os.environ.get("HERMES_PROFILE", "star")
    stable = task_id or os.environ.get("HERMES_SESSION_ID") or "default"
    return WORKFLOW_RE.sub("-", f"{profile}:{stable}")[:160]


def _bridge(command: str, payload: dict[str, Any], *, timeout: int | None = None) -> dict[str, Any]:
    if CONTROL_MODE not in {"firefox-ui-v1", "firefox-bidi-ui-v2"}:
        raise RuntimeError(f"unsupported secure browser control mode: {CONTROL_MODE}")
    kubeconfig = os.environ.get("KUBECONFIG", "").strip()
    if not kubeconfig:
        raise RuntimeError("Firefox UI bridge configuration missing: KUBECONFIG is not set for this profile")
    missing_kubeconfigs = [path for path in kubeconfig.split(os.pathsep) if path and not Path(path).is_file()]
    if missing_kubeconfigs:
        raise RuntimeError(f"Firefox UI bridge configuration invalid: KUBECONFIG file does not exist: {missing_kubeconfigs[0]}")
    argv = [
        "kubectl", "-n", NAMESPACE, "exec", "-i", WORKLOAD, "-c", CONTAINER,
        "--", "env", "DISPLAY=:1", BRIDGE_PATH, command,
    ]
    try:
        result = subprocess.run(
            argv,
            input=_json(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout or BRIDGE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Firefox UI bridge invocation failed: {exc}") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        if "localhost:8080" in message:
            raise RuntimeError("Firefox UI bridge Kubernetes configuration is unusable; verify KUBECONFIG selects a reachable cluster")
        raise RuntimeError(f"Firefox UI bridge failed ({result.returncode}): {message[:1000]}")
    if len(result.stdout.encode()) > MAX_RESULT_BYTES:
        raise RuntimeError("Firefox UI bridge response exceeded the bounded result size")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Firefox UI bridge returned invalid JSON: {result.stdout[:500]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Firefox UI bridge response was not an object")
    if parsed.get("status") == "error":
        raise RuntimeError(str(parsed.get("message") or parsed.get("error") or "Firefox UI bridge error"))
    return parsed


def _check_secure_browser() -> bool:
    return CONTROL_MODE in {"firefox-ui-v1", "firefox-bidi-ui-v2"} and bool(WORKLOAD) and bool(BRIDGE_PATH)


def _safe_call(operation: str, callback: Any) -> str:
    try:
        return _json(callback())
    except (RuntimeError, ValueError) as exc:
        return _json({
            "operation": operation,
            "status": "error",
            "error": "FIREFOX_UI_CONTROL_FAILED",
            "message": str(exc)[:1000],
            "protocol": CONTROL_MODE,
        })


def _save_screenshot(result: dict[str, Any], *, owner_only: bool = False) -> dict[str, Any]:
    encoded = str(result.pop("png_base64", ""))
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("Firefox UI bridge returned invalid screenshot data") from exc
    if not content.startswith(b"\x89PNG"):
        raise RuntimeError("Firefox UI bridge screenshot was not PNG")
    leaf = "owner-review" if owner_only else "evidence"
    evidence_dir = Path(get_hermes_home()) / "secure-browser" / leaf
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = evidence_dir / f"firefox-{int(time.time() * 1000)}.png"
    path.write_bytes(content)
    os.chmod(path, 0o600)
    result["image_path"] = str(path)
    result["protocol"] = CONTROL_MODE
    if owner_only:
        result.update({
            "owner_only": True,
            "generic_vision_allowed": False,
            "artifact_allowed": False,
            "same_message_with_structured_summary_required": True,
            "delivery_instruction": "Attach this image only to Joy's trusted owner chat in the same message as secure_browser_checkout_readback; never route it to vision/OCR, logs, evidence artifacts, Talon notifications, or another recipient.",
        })
    else:
        result["media"] = f"MEDIA:{path}"
    return result


def secure_browser_status_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _safe_call("status", lambda: {
        **_bridge("status", {}),
        "protocol": CONTROL_MODE,
        "instrumentation": {
            "webdriver": False, "marionette": CONTROL_MODE == "firefox-bidi-ui-v2",
            "bidi": CONTROL_MODE == "firefox-bidi-ui-v2", "cdp": False,
            "dom": CONTROL_MODE == "firefox-bidi-ui-v2",
        },
        "public_browser_url": PUBLIC_URL,
        "authorization_boundary": "Joy's direction to Star for the workflow; no per-click, checkout, or purchase approval ceremony",
        "sensitive_state_boundary": "Secrets remain in Firefox/Bitwarden and must not be passed as tool text or exposed from profile storage",
        "compatibility": {
            "version": CONTROL_MODE,
            "dom_selectors": CONTROL_MODE == "firefox-bidi-ui-v2",
            "javascript_query": False,
            "accessibility_locators": True,
            "coordinate_input": True,
        },
    })


def secure_browser_navigate_tool(args: dict[str, Any], task_id: str | None = None, **_kw: Any) -> str:
    def run() -> dict[str, Any]:
        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("url is required")
        payload = {
            "url": url,
            "workflow_id": _workflow_id(args, task_id),
            "lease_seconds": args.get("lease_seconds"),
        }
        if args.get("max_wait_seconds") is not None:
            payload["max_wait_seconds"] = args["max_wait_seconds"]
        return _bridge("navigate", payload, timeout=BRIDGE_TIMEOUT + 15)
    return _safe_call("navigate", run)


def secure_browser_page_snapshot_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _safe_call("snapshot", lambda: _bridge("snapshot", {}))


def secure_browser_current_page_summary_tool(args: dict[str, Any], **_kw: Any) -> str:
    def run() -> dict[str, Any]:
        snapshot = _bridge("snapshot", {})
        return {
            "operation": "current_page_summary",
            "status": "ok",
            "protocol": "firefox-ui-v1",
            "title": snapshot.get("title", ""),
            "url": snapshot.get("url", ""),
            "tab_count": snapshot.get("tab_count", 0),
            "selected_tab": next((tab.get("name") for tab in snapshot.get("tabs", []) if tab.get("selected")), ""),
            "visible_controls": snapshot.get("nodes", [])[:120],
            "truncated": bool(snapshot.get("truncated")) or len(snapshot.get("nodes", [])) > 120,
            "observation_boundary": snapshot.get("observation_boundary"),
        }
    return _safe_call("current_page_summary", run)


def secure_browser_wait_for_stable_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _safe_call("wait_for_stable", lambda: _bridge("wait", {
        "max_wait_seconds": args.get("max_wait_seconds", 6),
    }, timeout=BRIDGE_TIMEOUT + 15))


def secure_browser_checkout_readback_tool(args: dict[str, Any], **_kw: Any) -> str:
    def run() -> dict[str, Any]:
        nickname = " ".join(str(args.get("safe_item_nickname") or "").split())[:120]
        if not nickname:
            raise ValueError("safe_item_nickname is required")
        return _bridge("checkout_readback", {
            "safe_item_nickname": nickname,
            "max_wait_seconds": args.get("max_wait_seconds", 6),
        }, timeout=BRIDGE_TIMEOUT + 15)
    return _safe_call("checkout_readback", run)


def secure_browser_scroll_tool(args: dict[str, Any], task_id: str | None = None, **_kw: Any) -> str:
    return _safe_call("scroll", lambda: _bridge("scroll", {
        "workflow_id": _workflow_id(args, task_id),
        "direction": args.get("direction", "down"),
        "amount": args.get("amount", 1),
    }))


def secure_browser_owner_review_capture_tool(args: dict[str, Any], **_kw: Any) -> str:
    def run() -> dict[str, Any]:
        # Gateway multiplex sessions bind the served persona per turn; the
        # process environment may have no HERMES_PROFILE at all.
        profile = _session_env("HERMES_SESSION_PROFILE").lower()
        if profile != "star":
            raise ValueError("Owner-review captures are restricted to Star and must not enter Talon notifications")
        platform = _session_env("HERMES_SESSION_PLATFORM").lower()
        if platform != "telegram":
            raise ValueError("Owner-review captures are restricted to Joy's trusted Telegram owner channel")
        owner_chat = _telegram_chat_id(os.environ.get("SECURE_BROWSER_OWNER_TELEGRAM_CHAT", "") or os.environ.get("TELEGRAM_HOME_CHANNEL", ""))
        session_chat = _telegram_chat_id(_session_env("HERMES_SESSION_CHAT_ID"))
        if not owner_chat or not session_chat or session_chat != owner_chat:
            raise ValueError("Owner-review captures require the active trusted Telegram owner chat")
        nickname = " ".join(str(args.get("safe_item_nickname") or "").split())[:120]
        if not nickname:
            raise ValueError("safe_item_nickname is required")
        checkout_summary = _bridge("checkout_readback", {
            "safe_item_nickname": nickname,
            "max_wait_seconds": args.get("max_wait_seconds", 6),
        }, timeout=BRIDGE_TIMEOUT + 15)
        result = _save_screenshot(_bridge("screenshot", {}), owner_only=True)
        label = WORKFLOW_RE.sub("-", str(args.get("capture_label") or "review"))[:80]
        result["capture_label"] = label or "review"
        result["operation"] = "owner_review_capture"
        result["checkout_summary"] = checkout_summary
        return result
    return _safe_call("owner_review_capture", run)


def secure_browser_query_tool(args: dict[str, Any], **_kw: Any) -> str:
    if CONTROL_MODE == "firefox-bidi-ui-v2":
        def run() -> dict[str, Any]:
            from importlib import import_module
            secure_browser_bidi = import_module("tools.secure_browser_bidi")
            return secure_browser_bidi.query(_bridge("snapshot", {}), str(args.get("expression") or ""))
        return _safe_call("query", run)
    return _json({
        "operation": "query",
        "status": "unsupported",
        "error": "FIREFOX_UI_V1_NO_DOM_QUERY",
        "protocol": "firefox-ui-v1",
        "message": "Arbitrary JavaScript/DOM query is deliberately unavailable without browser-internal automation. Use secure_browser_page_snapshot, secure_browser_current_page_summary, screenshot/visual evidence, and accessibility locators.",
    })


def secure_browser_screenshot_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _safe_call("screenshot", lambda: _save_screenshot(_bridge("screenshot", {})))


def secure_browser_visual_evidence_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _safe_call("visual_evidence", lambda: {
        **_save_screenshot(_bridge("screenshot", {})),
        "operation": "visual_evidence",
        "capture_mode": "visible Firefox window through X11",
        "full_page": False,
        "compatibility_note": "firefox-ui-v1 captures the visible owner-shared desktop; DOM full-document capture and script-derived crops are intentionally unavailable",
    })


def secure_browser_click_tool(args: dict[str, Any], task_id: str | None = None, **_kw: Any) -> str:
    def run() -> dict[str, Any]:
        if CONTROL_MODE == "firefox-bidi-ui-v2" and args.get("selector"):
            from importlib import import_module
            secure_browser_bidi = import_module("tools.secure_browser_bidi")
            observed = _bridge("snapshot", {})
            point = secure_browser_bidi.selector_point(observed, str(args["selector"]))
            return _bridge("click", {
                "workflow_id": _workflow_id(args, task_id),
                "coordinate": point,
                "expected_url": observed.get("url"),
                "expected_generation": observed.get("browser_generation"),
                "expected_tab": next((tab.get("name") for tab in observed.get("tabs", []) if tab.get("selected")), None),
                "action_key": args.get("action_key") or args.get("idempotency_key"),
                "max_wait_seconds": args.get("max_wait_seconds"),
            }, timeout=BRIDGE_TIMEOUT + 15)
        if args.get("selector") and not args.get("locator"):
            return {
                "operation": "click", "status": "unsupported",
                "error": "FIREFOX_UI_V1_NO_CSS_SELECTORS", "protocol": "firefox-ui-v1",
                "message": "CSS selectors cannot honestly be resolved without browser-internal automation. Refresh secure_browser_page_snapshot and use its accessibility locator or a visible coordinate.",
            }
        payload = {
            "workflow_id": _workflow_id(args, task_id),
            "locator": args.get("locator"),
            "coordinate": args.get("coordinate"),
            "action_key": args.get("action_key") or args.get("idempotency_key"),
        }
        if args.get("max_wait_seconds") is not None:
            payload["max_wait_seconds"] = args["max_wait_seconds"]
        result = _bridge("click", payload, timeout=BRIDGE_TIMEOUT + 15)
        if args.get("approved_effect"):
            result["legacy_effect_label"] = str(args["approved_effect"])
            result["approval_note"] = "Effect labels are audit context only in firefox-ui-v1; Joy's workflow direction is the authorization boundary."
        return result
    return _safe_call("click", run)


def secure_browser_type_tool(args: dict[str, Any], task_id: str | None = None, **_kw: Any) -> str:
    def run() -> dict[str, Any]:
        if CONTROL_MODE == "firefox-bidi-ui-v2" and args.get("selector"):
            from importlib import import_module
            secure_browser_bidi = import_module("tools.secure_browser_bidi")
            observed = _bridge("snapshot", {})
            point = secure_browser_bidi.selector_point(observed, str(args["selector"]), field_only=True)
            return _bridge("type", {
                "workflow_id": _workflow_id(args, task_id),
                "coordinate": point,
                "expected_url": observed.get("url"),
                "expected_generation": observed.get("browser_generation"),
                "expected_tab": next((tab.get("name") for tab in observed.get("tabs", []) if tab.get("selected")), None),
                "text": args.get("text", ""),
            })
        if args.get("selector") and not args.get("locator"):
            return {
                "operation": "type", "status": "unsupported",
                "error": "FIREFOX_UI_V1_NO_CSS_SELECTORS", "protocol": "firefox-ui-v1",
                "message": "Refresh secure_browser_page_snapshot and use an accessibility locator. Never pass passwords, payment numbers, tokens, or other secrets as tool text; use Firefox/Bitwarden UI.",
            }
        return _bridge("type", {
            "workflow_id": _workflow_id(args, task_id),
            "locator": args.get("locator"),
            "text": args.get("text", ""),
        })
    return _safe_call("type", run)


def secure_browser_tab_lifecycle_tool(args: dict[str, Any], task_id: str | None = None, **_kw: Any) -> str:
    aliases = {
        "preview_cleanup": "status",
        "cleanup": "release",
        "mark_keep_open": "keep_open",
    }
    action = aliases.get(str(args.get("action") or "status"), str(args.get("action") or "status"))
    return _safe_call("tab_lifecycle", lambda: _bridge("tabs", {
        "action": action,
        "workflow_id": _workflow_id(args, task_id),
        "lease_seconds": args.get("lease_seconds"),
    }))


def secure_browser_guardrail_check_tool(args: dict[str, Any], **_kw: Any) -> str:
    operation = str(args.get("operation") or "browse")
    if operation in {"cookies", "storage", "profile", "raw_profile", "cdp", "webdriver", "bidi", "marionette", "javascript_query"}:
        return _json({
            "operation": "guardrail_check", "status": "blocked", "requested_operation": operation,
            "protocol": "firefox-ui-v1", "reason": "browser-internal automation and raw profile/session state are outside the architecture boundary",
        })
    return _json({
        "operation": "guardrail_check", "status": "allowed", "requested_operation": operation,
        "protocol": "firefox-ui-v1",
        "authorization_boundary": "Joy's direction to Star for the workflow; no redundant platform approval gate",
        "correctness": "Use accessibility/visual readback after every mutation and an action_key for exactly-once destructive or financial controls.",
    })


def secure_browser_owner_checkout_review_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _json({
        "operation": "owner_checkout_review", "status": "retired_no_extra_gate",
        "protocol": "firefox-ui-v1",
        "replacement_action": "Use secure_browser_visual_evidence or Joy's live browser.eyrie Kasm desktop in the same directed workflow; no owner-review approval ceremony is required.",
    })


def secure_browser_request_final_purchase_approval_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _json({
        "operation": "request_final_purchase_approval", "status": "retired_no_extra_gate",
        "protocol": "firefox-ui-v1",
        "replacement_action": "When Joy directed the workflow, use secure_browser_click with a fresh accessibility locator and stable action_key, then verify readback. No separate platform approval is required.",
    })


def secure_browser_execute_final_purchase_tool(args: dict[str, Any], **_kw: Any) -> str:
    return _json({
        "operation": "execute_final_purchase", "status": "retired_no_extra_gate",
        "protocol": "firefox-ui-v1",
        "replacement_action": "Use secure_browser_click with the final visible control's fresh accessibility locator and stable action_key. The action key supplies exactly-once correctness without a redundant approval gate.",
    })


SCHEMAS: list[tuple[dict[str, Any], Any]] = [
    ({"name": "secure_browser_status", "description": "Show the persistent Firefox UI-control status, continuity leases, non-instrumentation boundary, and compatibility version.", "parameters": {"type": "object", "properties": {}}}, secure_browser_status_tool),
    ({"name": "secure_browser_navigate", "description": "Navigate the canonical handoff tab in the owner-visible persistent Firefox by X11 address-bar input, then return transition-aware accessibility readback. Never creates a tab implicitly.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "workflow_id": {"type": "string"}, "lease_seconds": {"type": "integer"}, "max_wait_seconds": {"type": "number", "minimum": 0, "maximum": 15}}, "required": ["url"]}}, secure_browser_navigate_tool),
    ({"name": "secure_browser_page_snapshot", "description": "Read the owner-visible Firefox accessibility tree: ordinary page text, controls, values, states, and ephemeral locators. Secrets are redacted; DOM, cookies and browser profile data are not exposed.", "parameters": {"type": "object", "properties": {}}}, secure_browser_page_snapshot_tool),
    ({"name": "secure_browser_current_page_summary", "description": "Return a bounded accessibility-based page summary including ordinary readable content and controls; use page_snapshot for more nodes.", "parameters": {"type": "object", "properties": {}}}, secure_browser_current_page_summary_tool),
    ({"name": "secure_browser_wait_for_stable", "description": "Wait a bounded interval for the visible Firefox accessibility state to settle. Deterministically reports stable, in_flight, terminal_success, or terminal_error; delivery alone is never confirmation.", "parameters": {"type": "object", "properties": {"max_wait_seconds": {"type": "number", "minimum": 0, "maximum": 15}}}}, secure_browser_wait_for_stable_tool),
    ({"name": "secure_browser_checkout_readback", "description": "Return sanitized first-class checkout/post-purchase fields from visible AT-SPI readback: retailer, safe item nickname, selected variant, quantity, subtotal, shipping, tax, total, and confirmation state. Never returns owner identity, email, address, payment details, raw order IDs, or raw page text.", "parameters": {"type": "object", "properties": {"safe_item_nickname": {"type": "string", "maxLength": 120}, "max_wait_seconds": {"type": "number", "minimum": 0, "maximum": 15}}, "required": ["safe_item_nickname"]}}, secure_browser_checkout_readback_tool),
    ({"name": "secure_browser_scroll", "description": "Scroll the canonical owner-visible Firefox workflow by bounded visible page increments, then return transition-aware readback.", "parameters": {"type": "object", "properties": {"workflow_id": {"type": "string"}, "direction": {"type": "string", "enum": ["up", "down"]}, "amount": {"type": "integer", "minimum": 1, "maximum": 6}}}}, secure_browser_scroll_tool),
    ({"name": "secure_browser_owner_review_capture", "description": "Capture one visible pre-purchase Firefox viewport and pair it with sanitized structured checkout readback for owner-only delivery in the active trusted Joy Telegram chat. The image must never enter generic vision/OCR, logs, task evidence/artifacts, Talon notifications, or another recipient; capture multiple visible viewports with secure_browser_scroll when needed.", "parameters": {"type": "object", "properties": {"capture_label": {"type": "string", "maxLength": 80}, "safe_item_nickname": {"type": "string", "maxLength": 120}, "max_wait_seconds": {"type": "number", "minimum": 0, "maximum": 15}}, "required": ["safe_item_nickname"]}}, secure_browser_owner_review_capture_tool),
    ({"name": "secure_browser_query", "description": "Versioned compatibility endpoint. firefox-ui-v1 deliberately rejects arbitrary JavaScript/DOM queries and directs callers to accessibility/visual observation.", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}}}, secure_browser_query_tool),
    ({"name": "secure_browser_screenshot", "description": "Capture the visible persistent Firefox window through X11 and return a local PNG artifact.", "parameters": {"type": "object", "properties": {}}}, secure_browser_screenshot_tool),
    ({"name": "secure_browser_visual_evidence", "description": "Capture visible-window evidence from the persistent Firefox desktop without browser instrumentation.", "parameters": {"type": "object", "properties": {}}}, secure_browser_visual_evidence_tool),
    ({"name": "secure_browser_click", "description": "Click a fresh accessibility locator or visible coordinate in the canonical Firefox handoff tab, then return bounded transition-aware readback. A delivered click is never confirmed completion. Joy's workflow direction is the authorization boundary; use action_key for exactly-once destructive/financial actions.", "parameters": {"type": "object", "properties": {"locator": {"type": "string"}, "coordinate": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}, "workflow_id": {"type": "string"}, "action_key": {"type": "string"}, "idempotency_key": {"type": "string"}, "max_wait_seconds": {"type": "number", "minimum": 0, "maximum": 15}, "selector": {"type": "string", "description": "Legacy-only; rejected in firefox-ui-v1"}, "approved_effect": {"type": "string", "description": "Legacy audit label; not an approval gate"}}, "anyOf": [{"required": ["locator"]}, {"required": ["coordinate"]}, {"required": ["selector"]}]}}, secure_browser_click_tool),
    ({"name": "secure_browser_type", "description": "Type bounded non-secret text into a fresh accessibility locator and return redacted readback. Never pass passwords, payment numbers, tokens, or other secrets; operate Firefox/Bitwarden UI instead.", "parameters": {"type": "object", "properties": {"locator": {"type": "string"}, "selector": {"type": "string", "description": "Legacy-only; rejected in firefox-ui-v1"}, "text": {"type": "string", "maxLength": 4096}, "workflow_id": {"type": "string"}}, "required": ["text"]}}, secure_browser_type_tool),
    ({"name": "secure_browser_tab_lifecycle", "description": "Acquire, keep open, inspect, or release the canonical workflow tab. Ownership is durable; uncertain or Joy-owned tabs are preserved; hard caps refuse new tabs rather than closing unowned tabs.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["status", "acquire", "keep_open", "release", "preview_cleanup", "cleanup", "mark_keep_open"]}, "workflow_id": {"type": "string"}, "lease_seconds": {"type": "integer"}}}}, secure_browser_tab_lifecycle_tool),
    ({"name": "secure_browser_guardrail_check", "description": "Describe the firefox-ui-v1 boundary. Joy-directed browser UI actions are allowed without redundant approval gates; raw browser/profile/automation access is blocked.", "parameters": {"type": "object", "properties": {"operation": {"type": "string"}}}}, secure_browser_guardrail_check_tool),
    ({"name": "secure_browser_owner_checkout_review", "description": "Retired compatibility endpoint: owner review is no longer an extra approval gate.", "parameters": {"type": "object", "properties": {}}}, secure_browser_owner_checkout_review_tool),
    ({"name": "secure_browser_request_final_purchase_approval", "description": "Retired compatibility endpoint: Joy's workflow direction is the authorization boundary.", "parameters": {"type": "object", "properties": {}}}, secure_browser_request_final_purchase_approval_tool),
    ({"name": "secure_browser_execute_final_purchase", "description": "Retired compatibility endpoint. Use secure_browser_click with a fresh locator and action_key for exactly-once execution.", "parameters": {"type": "object", "properties": {}}}, secure_browser_execute_final_purchase_tool),
]

first_schema, first_handler = SCHEMAS[0]
registry.register(
    name=first_schema["name"],
    toolset=TOOLSET,
    schema=first_schema,
    handler=first_handler,
    check_fn=_check_secure_browser,
    description=first_schema["description"],
)

# Hermes discovers built-in tool modules by looking for a direct top-level
# registry.register() call before importing them. Keep the first registration
# explicit above; once imported, register the remainder from the shared table.
for schema, handler in SCHEMAS[1:]:
    registry.register(
        name=schema["name"],
        toolset=TOOLSET,
        schema=schema,
        handler=handler,
        check_fn=_check_secure_browser,
        description=schema["description"],
    )


if __name__ == "__main__":
    assert _check_secure_browser()
    assert json.loads(secure_browser_query_tool({"expression": "document.title"}))["error"] == "FIREFOX_UI_V1_NO_DOM_QUERY"
    assert json.loads(secure_browser_guardrail_check_tool({"operation": "checkout"}))["status"] == "allowed"
    assert json.loads(secure_browser_guardrail_check_tool({"operation": "cookies"}))["status"] == "blocked"
    assert json.loads(secure_browser_request_final_purchase_approval_tool({}))["status"] == "retired_no_extra_gate"
    print("secure_browser firefox-ui-v1 smoke ok")
