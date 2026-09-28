#!/usr/bin/env python3
"""Compatibility checks for the firefox-ui-v1 Hermes adapter."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "files/app/hermes/secure_browser_tool.py"


class DummyRegistry:
    def __init__(self) -> None:
        self.names: list[str] = []

    def register(self, **kwargs: Any) -> None:
        self.names.append(kwargs["name"])


def load_tool() -> tuple[Any, DummyRegistry]:
    registry = DummyRegistry()
    tools = types.ModuleType("tools")
    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", registry)
    sys.modules["tools"] = tools
    sys.modules["tools.registry"] = registry_module
    spec = importlib.util.spec_from_file_location("secure_browser_ui_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, registry


def parsed(value: str) -> dict[str, Any]:
    result = json.loads(value)
    assert isinstance(result, dict)
    return result


def test_tool_module_has_top_level_registry_registration_for_discovery() -> None:
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    assert any(
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "register"
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == "registry"
        for statement in tree.body
    )


def test_contracts_register_and_dom_incompatibility_is_explicit() -> None:
    module, registry = load_tool()
    assert {
        "secure_browser_status", "secure_browser_navigate", "secure_browser_page_snapshot",
        "secure_browser_current_page_summary", "secure_browser_query", "secure_browser_click",
        "secure_browser_type", "secure_browser_screenshot", "secure_browser_visual_evidence",
        "secure_browser_tab_lifecycle", "secure_browser_guardrail_check",
        "secure_browser_owner_checkout_review", "secure_browser_request_final_purchase_approval",
        "secure_browser_execute_final_purchase",
        "secure_browser_wait_for_stable", "secure_browser_checkout_readback",
        "secure_browser_scroll", "secure_browser_owner_review_capture",
    } <= set(registry.names)
    query = parsed(module.secure_browser_query_tool({"expression": "document.title"}))
    assert query["status"] == "unsupported"
    assert query["error"] == "FIREFOX_UI_V1_NO_DOM_QUERY"
    selector = parsed(module.secure_browser_click_tool({"selector": "button"}))
    assert selector["error"] == "FIREFOX_UI_V1_NO_CSS_SELECTORS"


def test_joy_directed_checkout_and_purchase_have_no_extra_approval_gate() -> None:
    module, _ = load_tool()
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_bridge(command: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        calls.append((command, payload))
        return {"operation": command, "status": "delivered", "readback": {"tab_count": 1}}

    module._bridge = fake_bridge
    check = parsed(module.secure_browser_guardrail_check_tool({"operation": "purchase"}))
    assert check["status"] == "allowed"
    checkout = parsed(module.secure_browser_owner_checkout_review_tool({"workflow_id": "fixture"}))
    approval = parsed(module.secure_browser_request_final_purchase_approval_tool({"workflow_id": "fixture"}))
    purchase = parsed(module.secure_browser_execute_final_purchase_tool({"workflow_id": "fixture"}))
    assert checkout["status"] == approval["status"] == "retired_no_extra_gate"
    assert purchase["status"] == "retired_no_extra_gate"
    click = parsed(module.secure_browser_click_tool({
        "workflow_id": "fixture", "locator": "ax:1:2:0123456789ab", "action_key": "fixture-order",
    }))
    assert click["status"] == "delivered"
    assert calls[-1] == ("click", {"workflow_id": "fixture", "locator": "ax:1:2:0123456789ab", "coordinate": None, "action_key": "fixture-order"})


def test_missing_kubeconfig_reports_profile_configuration_error_without_kubectl_noise() -> None:
    module, _ = load_tool()
    original_home = module.os.environ.get("HOME")
    original_kubeconfig = module.os.environ.pop("KUBECONFIG", None)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            module.os.environ["HOME"] = tmpdir
            result = parsed(module.secure_browser_status_tool({}))
    finally:
        if original_home is None:
            module.os.environ.pop("HOME", None)
        else:
            module.os.environ["HOME"] = original_home
        if original_kubeconfig is not None:
            module.os.environ["KUBECONFIG"] = original_kubeconfig

    assert result["error"] == "FIREFOX_UI_CONTROL_FAILED"
    assert result["message"] == "Firefox UI bridge configuration missing: KUBECONFIG is not set for this profile"
    assert "localhost:8080" not in result["message"]
    assert "memcache.go" not in result["message"]


def test_bridge_error_stdout_is_not_masked_by_kubectl_exit_line() -> None:
    module, _ = load_tool()
    original_kubeconfig = module.os.environ.get("KUBECONFIG")
    original_run = module.subprocess.run
    try:
        with tempfile.NamedTemporaryFile() as kubeconfig:
            module.os.environ["KUBECONFIG"] = kubeconfig.name
            module.subprocess.run = lambda *_args, **_kwargs: subprocess.CompletedProcess(
                [], 1, '{"status":"error","error":"RuntimeError","message":"canonical tab ownership is uncertain"}',
                'command terminated with exit code 1',
            )
            result = parsed(module.secure_browser_navigate_tool({"url": "https://example.test/"}))
    finally:
        module.subprocess.run = original_run
        if original_kubeconfig is None:
            module.os.environ.pop("KUBECONFIG", None)
        else:
            module.os.environ["KUBECONFIG"] = original_kubeconfig
    assert result["message"] == "canonical tab ownership is uncertain"

def test_missing_kubeconfig_file_reports_exact_dependency_without_kubectl_noise() -> None:
    module, _ = load_tool()
    original_kubeconfig = module.os.environ.get("KUBECONFIG")
    try:
        module.os.environ["KUBECONFIG"] = "/missing/firefox-ui-kubeconfig"
        result = parsed(module.secure_browser_status_tool({}))
    finally:
        if original_kubeconfig is None:
            module.os.environ.pop("KUBECONFIG", None)
        else:
            module.os.environ["KUBECONFIG"] = original_kubeconfig

    assert result["message"] == "Firefox UI bridge configuration invalid: KUBECONFIG file does not exist: /missing/firefox-ui-kubeconfig"
    assert "localhost:8080" not in result["message"]
    assert "memcache.go" not in result["message"]


def test_unusable_kubeconfig_reports_configuration_error_without_localhost_fallback_noise() -> None:
    module, _ = load_tool()
    original_kubeconfig = module.os.environ.get("KUBECONFIG")
    try:
        with tempfile.NamedTemporaryFile() as kubeconfig:
            module.os.environ["KUBECONFIG"] = kubeconfig.name
            result = parsed(module.secure_browser_status_tool({}))
    finally:
        if original_kubeconfig is None:
            module.os.environ.pop("KUBECONFIG", None)
        else:
            module.os.environ["KUBECONFIG"] = original_kubeconfig

    assert result["message"] == "Firefox UI bridge Kubernetes configuration is unusable; verify KUBECONFIG selects a reachable cluster"
    assert "localhost:8080" not in result["message"]
    assert "memcache.go" not in result["message"]


def test_screenshot_is_private_and_tab_aliases_migrate() -> None:
    module, _ = load_tool()
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_bridge(command: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        calls.append((command, payload))
        if command == "screenshot":
            return {"operation": "screenshot", "status": "ok", "png_base64": tiny_png}
        return {"operation": command, "status": "ok"}

    module._bridge = fake_bridge
    with tempfile.TemporaryDirectory() as tmpdir:
        module.get_hermes_home = lambda: Path(tmpdir)
        screenshot = parsed(module.secure_browser_screenshot_tool({}))
        path = Path(screenshot["image_path"])
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600
    parsed(module.secure_browser_tab_lifecycle_tool({"action": "cleanup", "workflow_id": "fixture"}))
    assert calls[-1][0] == "tabs"
    assert calls[-1][1]["action"] == "release"


def test_checkout_readback_and_wait_are_first_class_bridge_operations() -> None:
    module, _ = load_tool()
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_bridge(command: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        calls.append((command, payload))
        return {"operation": command, "status": "ok"}

    module._bridge = fake_bridge
    parsed(module.secure_browser_wait_for_stable_tool({"max_wait_seconds": 7}))
    parsed(module.secure_browser_checkout_readback_tool({"safe_item_nickname": "ONNO hemp tee", "max_wait_seconds": 5}))
    parsed(module.secure_browser_scroll_tool({"direction": "down", "amount": 2, "workflow_id": "fixture"}))
    assert calls == [
        ("wait", {"max_wait_seconds": 7}),
        ("checkout_readback", {"safe_item_nickname": "ONNO hemp tee", "max_wait_seconds": 5}),
        ("scroll", {"workflow_id": "fixture", "direction": "down", "amount": 2}),
    ]


def test_owner_review_capture_is_private_owner_only_and_not_generic_evidence() -> None:
    module, _ = load_tool()
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    def fake_bridge(command: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        if command == "checkout_readback":
            return {
                "operation": command, "status": "ok", "retailer": "shop.example",
                "safe_item_nickname": payload["safe_item_nickname"], "variant": ["Navy", "Medium"],
                "quantity": 1, "subtotal": "$50.00", "shipping": "$5.00", "tax": "$2.24",
                "total": "$57.24", "confirmation_status": "not_confirmed",
            }
        return {"operation": command, "status": "ok", "png_base64": tiny_png}

    module._bridge = fake_bridge
    original_profile = module.os.environ.get("HERMES_PROFILE")
    original_session_profile = module.os.environ.get("HERMES_SESSION_PROFILE")
    original_platform = module.os.environ.get("HERMES_SESSION_PLATFORM")
    original_chat = module.os.environ.get("HERMES_SESSION_CHAT_ID")
    original_home_channel = module.os.environ.get("TELEGRAM_HOME_CHANNEL")
    with tempfile.TemporaryDirectory() as tmpdir:
        module.get_hermes_home = lambda: Path(tmpdir)
        module.os.environ["HERMES_PROFILE"] = "star"
        module.os.environ["HERMES_SESSION_PROFILE"] = "star"
        module.os.environ["HERMES_SESSION_PLATFORM"] = "telegram"
        module.os.environ["HERMES_SESSION_CHAT_ID"] = "12345"
        module.os.environ["TELEGRAM_HOME_CHANNEL"] = "12345"
        module._session_env = lambda key: module.os.environ.get(key, "")
        capture = parsed(module.secure_browser_owner_review_capture_tool({
            "capture_label": "review-1", "safe_item_nickname": "fixture item",
        }))
        path = Path(capture["image_path"])
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.name == "owner-review"
        assert capture["owner_only"] is True
        assert capture["generic_vision_allowed"] is False
        assert capture["artifact_allowed"] is False
        assert capture["same_message_with_structured_summary_required"] is True
        assert capture["checkout_summary"]["total"] == "$57.24"
        assert "media" not in capture
    for key, original in (
        ("HERMES_PROFILE", original_profile),
        ("HERMES_SESSION_PROFILE", original_session_profile),
        ("HERMES_SESSION_PLATFORM", original_platform),
        ("HERMES_SESSION_CHAT_ID", original_chat),
        ("TELEGRAM_HOME_CHANNEL", original_home_channel),
    ):
        if original is None:
            module.os.environ.pop(key, None)
        else:
            module.os.environ[key] = original


def test_owner_review_capture_refuses_missing_or_untrusted_owner_context() -> None:
    module, _ = load_tool()
    called = False

    def fake_bridge(_command: str, _payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    module._bridge = fake_bridge
    module._session_env = lambda key: module.os.environ.get(key, "")
    keys = ("HERMES_PROFILE", "HERMES_SESSION_PROFILE", "HERMES_SESSION_PLATFORM", "HERMES_SESSION_CHAT_ID", "TELEGRAM_HOME_CHANNEL")
    originals = {key: module.os.environ.get(key) for key in keys}
    try:
        for key in keys:
            module.os.environ.pop(key, None)
        missing = parsed(module.secure_browser_owner_review_capture_tool({"safe_item_nickname": "fixture"}))
        module.os.environ["HERMES_PROFILE"] = "talon"
        module.os.environ["HERMES_SESSION_PROFILE"] = "talon"
        module.os.environ["HERMES_SESSION_PLATFORM"] = "telegram"
        module.os.environ["HERMES_SESSION_CHAT_ID"] = "12345"
        module.os.environ["TELEGRAM_HOME_CHANNEL"] = "12345"
        talon = parsed(module.secure_browser_owner_review_capture_tool({"safe_item_nickname": "fixture"}))
        module.os.environ["HERMES_PROFILE"] = "star"
        module.os.environ["HERMES_SESSION_PROFILE"] = "star"
        module.os.environ["HERMES_SESSION_PLATFORM"] = "cli"
        wrong_platform = parsed(module.secure_browser_owner_review_capture_tool({"safe_item_nickname": "fixture"}))
        module.os.environ["HERMES_SESSION_PLATFORM"] = "telegram"
        module.os.environ["HERMES_SESSION_CHAT_ID"] = "99999"
        wrong_recipient = parsed(module.secure_browser_owner_review_capture_tool({"safe_item_nickname": "fixture"}))
    finally:
        for key, original in originals.items():
            if original is None:
                module.os.environ.pop(key, None)
            else:
                module.os.environ[key] = original
    assert missing["status"] == talon["status"] == wrong_platform["status"] == wrong_recipient["status"] == "error"
    assert "Star" in talon["message"]
    assert "Telegram" in wrong_platform["message"]
    assert "owner" in wrong_recipient["message"].lower()
    assert called is False


if __name__ == "__main__":
    for test_name in sorted(name for name in globals() if name.startswith("test_")):
        globals()[test_name]()
