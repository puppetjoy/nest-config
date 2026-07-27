#!/usr/bin/env python3
"""Regression checks for exposed secure-browser guardrail semantics."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURE_BROWSER_TOOL = REPO_ROOT / "files/app/hermes/secure_browser_tool.py"


class DummyRegistry:
    def register(self, **_kwargs: Any) -> None:
        return None


def load_tool_module() -> Any:
    websockets_module = types.ModuleType("websockets")
    websockets_sync_module = types.ModuleType("websockets.sync")
    websockets_client_module = types.ModuleType("websockets.sync.client")
    setattr(websockets_client_module, "connect", lambda *_args, **_kwargs: None)
    setattr(websockets_sync_module, "client", websockets_client_module)
    setattr(websockets_module, "sync", websockets_sync_module)
    sys.modules.setdefault("websockets", websockets_module)
    sys.modules.setdefault("websockets.sync", websockets_sync_module)
    sys.modules.setdefault("websockets.sync.client", websockets_client_module)

    tools_module = types.ModuleType("tools")
    registry_module = types.ModuleType("tools.registry")
    setattr(registry_module, "registry", DummyRegistry())
    sys.modules.setdefault("tools", tools_module)
    sys.modules["tools.registry"] = registry_module

    with tempfile.TemporaryDirectory() as tmpdir:
        sys.modules.pop("secure_browser_guardrails_under_test", None)
        spec = importlib.util.spec_from_file_location("secure_browser_guardrails_under_test", SECURE_BROWSER_TOOL)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        setattr(module, "OWNERSHIP_STATE_PATH", str(Path(tmpdir) / "secure-browser-tabs.json"))
        return module


def test_guardrail_check_preserves_human_takeover_hard_stops() -> None:
    module = load_tool_module()

    for operation in ["login", "payment", "wallet", "address", "passkey", "2fa", "captcha"]:
        result = json.loads(module.secure_browser_guardrail_check_tool({"operation": operation}))
        assert result["allowed"] is False
        assert result["error"] == "OPERATION_NOT_ALLOWED"


def test_guardrail_check_keeps_checkout_prep_and_final_purchase_boundaries() -> None:
    module = load_tool_module()

    checkout = json.loads(module.secure_browser_guardrail_check_tool({"operation": "checkout"}))
    assert checkout["allowed"] is True
    assert checkout["boundary"] == "checkout_prep_only"

    approval = json.loads(module.secure_browser_guardrail_check_tool({"operation": "request_final_purchase_approval"}))
    assert approval["allowed"] is True
    assert approval["trusted_approval_required"] is True

    place_order = json.loads(module.secure_browser_guardrail_check_tool({"operation": "place_order"}))
    assert place_order["allowed"] is False
    assert place_order["trusted_approval_required"] is True


if __name__ == "__main__":
    test_guardrail_check_preserves_human_takeover_hard_stops()
    test_guardrail_check_keeps_checkout_prep_and_final_purchase_boundaries()