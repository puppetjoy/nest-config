#!/usr/bin/env python3
"""Regression checks for exposed secure-browser guardrail semantics."""

from __future__ import annotations

import importlib.util
import json
import os
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


def test_final_purchase_approval_request_targets_current_executor_profile() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_profile = os.environ.get("HERMES_PROFILE")
        os.environ["HERMES_PROFILE"] = "star"
        try:
            module = load_tool_module()
            setattr(module, "FINAL_PURCHASE_STATE_PATH", str(Path(tmpdir) / "final-purchase-state.json"))
            captured: dict[str, dict[str, Any]] = {}

            def fake_submit(payload: dict[str, Any]) -> str:
                captured["submit"] = payload
                return json.dumps({"request_id": "ar-20260101-000000-deadbe", "request": {"id": "ar-20260101-000000-deadbe"}})

            def fake_propose(payload: dict[str, Any]) -> str:
                captured["propose"] = payload
                return json.dumps({"request": {"id": payload["request_id"]}})

            agent_request_module = types.ModuleType("tools.agent_request_tool")
            setattr(agent_request_module, "agent_request_submit_tool", fake_submit)
            setattr(agent_request_module, "agent_request_propose_tool", fake_propose)
            sys.modules["tools.agent_request_tool"] = agent_request_module
            setattr(module, "_retire_prior_final_purchase_approval_requests", lambda *_args, **_kwargs: [])

            result = module._submit_final_purchase_approval_request(
                {
                    "url": "https://www.amazon.com/gp/buy/spc/handlers/display.html",
                    "page_title": "Review your order",
                    "items": ["Pipe screens Qty: 1"],
                    "delivery": ["Arrives tomorrow"],
                },
                "a" * 64,
                "b" * 64,
                "owner-review-test",
                "Star canary",
            )

            assert result["status"] == "approval_requested"
            assert captured["submit"]["target"] == "star"
            assert "executor_profile: star" in captured["submit"]["context"]
            assert "star must execute exactly one final Place Order action" in captured["submit"]["request"]
            assert captured["propose"]["response_to_requester"].startswith("If approved, star will execute")

            with module._final_purchase_state_lock() as handle:
                state = module._load_final_purchase_state(handle)
            stored = next(iter(state["approval_requests"].values()))
            assert stored["executor_profile"] == "star"
        finally:
            if previous_profile is None:
                os.environ.pop("HERMES_PROFILE", None)
            else:
                os.environ["HERMES_PROFILE"] = previous_profile


if __name__ == "__main__":
    test_guardrail_check_preserves_human_takeover_hard_stops()
    test_guardrail_check_keeps_checkout_prep_and_final_purchase_boundaries()
    test_final_purchase_approval_request_targets_current_executor_profile()