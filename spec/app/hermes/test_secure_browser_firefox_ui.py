#!/usr/bin/env python3
"""Compatibility checks for the firefox-ui-v1 Hermes adapter."""

from __future__ import annotations

import importlib.util
import json
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


def test_contracts_register_and_dom_incompatibility_is_explicit() -> None:
    module, registry = load_tool()
    assert {
        "secure_browser_status", "secure_browser_navigate", "secure_browser_page_snapshot",
        "secure_browser_current_page_summary", "secure_browser_query", "secure_browser_click",
        "secure_browser_type", "secure_browser_screenshot", "secure_browser_visual_evidence",
        "secure_browser_tab_lifecycle", "secure_browser_guardrail_check",
        "secure_browser_owner_checkout_review", "secure_browser_request_final_purchase_approval",
        "secure_browser_execute_final_purchase",
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


if __name__ == "__main__":
    test_contracts_register_and_dom_incompatibility_is_explicit()
    test_joy_directed_checkout_and_purchase_have_no_extra_approval_gate()
    test_screenshot_is_private_and_tab_aliases_migrate()
