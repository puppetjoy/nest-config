#!/usr/bin/env python3
"""Regression checks for Star retail order refresh result compaction."""

from __future__ import annotations

import importlib.util
import json
from contextlib import redirect_stdout
from io import StringIO
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURE_BROWSER_TOOL = REPO_ROOT / "files/app/hermes/secure_browser_tool.py"
ORDER_REFRESH_RUNNER = REPO_ROOT / "files/app/hermes/star-order-refresh-runner.py"


class DummyRegistry:
    def register(self, **_kwargs: Any) -> None:
        return None


def install_import_stubs() -> None:
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


def load_module(path: Path, name: str) -> Any:
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def large_refresh_result(order_count: int = 50) -> dict[str, Any]:
    bulky_fact = "Arriving Tuesday via sanitized refresh evidence. " * 80
    due_orders = [
        {
            "handle": f"safe-order-{idx}",
            "item_nickname": f"safe item nickname {idx} {bulky_fact}",
            "status": "shipped",
            "eta_window": "Arriving Tuesday",
            "refresh_sources": ["amazon_your_orders", "gmail_order_email", "carrier_page"],
        }
        for idx in range(order_count)
    ]
    refreshed = []
    for idx, due in enumerate(due_orders):
        refreshed.append(
            {
                "handle": due["handle"],
                "attempts": [
                    {"source": "amazon_your_orders", "status": "blocked", "safe_delivery_facts": [bulky_fact] * 4},
                    {"source": "gmail_order_email", "status": "ok", "safe_delivery_facts": [bulky_fact] * 4},
                ],
                "applied": {
                    "observation": {
                        "source": "gmail_order_email",
                        "status": "ok",
                        "order_status": "shipped",
                        "eta_window": "Arriving Tuesday",
                        "safe_delivery_facts": [bulky_fact] * 6,
                    },
                    "preview": {
                        "notification_decision": {
                            "should_notify": idx == 0,
                            "event_type": "eta_changed" if idx == 0 else "no_material_change",
                            "already_notified": idx != 0,
                            "reasons": [bulky_fact] * 4,
                        },
                        "candidate_order": {**due, "notes": bulky_fact},
                    },
                    "stored_order": {**due, "notes": bulky_fact},
                    "notification": {"status": "sent" if idx == 0 else "not_required", "message": bulky_fact},
                },
            }
        )
    return {
        "operation": "retail_order_refresh_run",
        "status": "ok",
        "plan": {"operation": "retail_order_refresh_plan", "status": "ok", "due_orders": due_orders},
        "refreshed": refreshed,
        "notifications_sent": 1,
        "privacy_boundary": bulky_fact,
    }


def test_retail_order_refresh_run_compacts_large_tool_result_without_budget_error() -> None:
    install_import_stubs()
    with tempfile.TemporaryDirectory() as tmpdir:
        module = load_module(SECURE_BROWSER_TOOL, "secure_browser_refresh_compaction_under_test")
        setattr(module, "OWNERSHIP_STATE_PATH", str(Path(tmpdir) / "secure-browser-tabs.json"))
        result = json.loads(module._json(large_refresh_result()))

    assert result["operation"] == "retail_order_refresh_run"
    assert result["status"] == "ok"
    assert result["result_truncated"] is True
    assert "error" not in result
    assert len(json.dumps(result, ensure_ascii=False, sort_keys=True)) <= module.MAX_RESULT_CHARS
    assert result["due_orders_count"] == 50
    assert result["refreshed_count"] == 50
    assert result["refreshed_returned"] == 20
    assert result["notifications_sent"] == 1
    assert result["notification_status_counts"]["sent"] == 1
    assert "plan" not in result
    assert "stored_order" not in json.dumps(result)
    assert "candidate_order" not in json.dumps(result)


def test_star_order_refresh_runner_json_output_is_compact() -> None:
    runner = load_module(ORDER_REFRESH_RUNNER, "star_order_refresh_runner_under_test")

    class FakeTool:
        @staticmethod
        def retail_order_refresh_run_tool(args: dict[str, Any]) -> str:
            assert args == {"send_notifications": True, "limit": 20}
            return json.dumps(large_refresh_result(order_count=8), ensure_ascii=False)

    original_load_tool_module = runner._load_tool_module
    runner._load_tool_module = lambda: FakeTool
    stdout = StringIO()
    try:
        with redirect_stdout(stdout):
            assert runner.main(["--json"]) == 0
    finally:
        runner._load_tool_module = original_load_tool_module

    output = json.loads(stdout.getvalue())
    assert output["operation"] == "retail_order_refresh_run"
    assert output["due_orders_count"] == 8
    assert output["refreshed_count"] == 8
    assert output["notifications_sent"] == 1
    assert "plan" not in output
    assert "refreshed" not in output
    assert len(json.dumps(output, ensure_ascii=False, sort_keys=True)) < 2000


if __name__ == "__main__":
    test_retail_order_refresh_run_compacts_large_tool_result_without_budget_error()
    test_star_order_refresh_runner_json_output_is_compact()
