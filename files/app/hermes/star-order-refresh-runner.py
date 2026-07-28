#!/opt/hermes-agent/venv/bin/python
"""Run Star's safe retail-order refresh loop.

This small systemd-friendly wrapper calls the retail_order tool entry point in
process so the scheduled unit can reuse Star's profile environment and Telegram
settings without exposing browser/Gmail/carrier raw data in command output.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_tool_module():
    # Source checkouts execute this helper beside secure_browser_tool.py;
    # deployed units run with PYTHONPATH=/opt/hermes-agent/src and import the
    # Puppet-copied tool from tools.secure_browser_tool.
    here = Path(__file__).resolve()
    local_tool = here.with_name("secure_browser_tool.py")
    if local_tool.exists():
        spec = importlib.util.spec_from_file_location("secure_browser_tool", local_tool)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    for parent in here.parents:
        candidate = parent / "tools"
        if (candidate / "secure_browser_tool.py").exists():
            sys.path.insert(0, str(parent))
            from tools import secure_browser_tool  # type: ignore[import-not-found]

            return secure_browser_tool
    from tools import secure_browser_tool  # type: ignore[import-not-found]

    return secure_browser_tool


def _compact_result(result: dict) -> dict:
    """Keep scheduled journal output compact while preserving outcomes."""

    if result.get("operation") != "retail_order_refresh_run":
        return result
    plan_value = result.get("plan")
    plan = plan_value if isinstance(plan_value, dict) else {}
    due_orders_value = plan.get("due_orders")
    due_orders = due_orders_value if isinstance(due_orders_value, list) else []
    refreshed_value = result.get("refreshed")
    refreshed = refreshed_value if isinstance(refreshed_value, list) else []
    due_orders_count = result.get("due_orders_count") if isinstance(result.get("due_orders_count"), int) else len(due_orders)
    refreshed_count = result.get("refreshed_count") if isinstance(result.get("refreshed_count"), int) else len(refreshed)
    applied_count_value = result.get("applied_count")
    applied_count = applied_count_value if isinstance(applied_count_value, int) else 0
    notification_status_counts_value = result.get("notification_status_counts")
    notification_status_counts = notification_status_counts_value if isinstance(notification_status_counts_value, dict) else {}
    if notification_status_counts and applied_count:
        return {
            "operation": "retail_order_refresh_run",
            "status": result.get("status"),
            "due_orders_count": due_orders_count,
            "refreshed_count": refreshed_count,
            "applied_count": applied_count,
            "notifications_sent": result.get("notifications_sent", 0),
            "notification_status_counts": notification_status_counts,
            "privacy_boundary": "Scheduled output is compact and sanitized; material notifications are sent through the retail order notification path.",
            "result_truncated": True,
        }
    for item in refreshed:
        if not isinstance(item, dict):
            continue
        applied_value = item.get("applied")
        applied = applied_value if isinstance(applied_value, dict) else {}
        if applied:
            applied_count += 1
        notification_value = applied.get("notification")
        notification = notification_value if isinstance(notification_value, dict) else {}
        status = str(notification.get("status") or "")
        if status:
            notification_status_counts[status] = notification_status_counts.get(status, 0) + 1
    return {
        "operation": "retail_order_refresh_run",
        "status": result.get("status"),
        "due_orders_count": due_orders_count,
        "refreshed_count": refreshed_count,
        "applied_count": applied_count,
        "notifications_sent": result.get("notifications_sent", 0),
        "notification_status_counts": notification_status_counts,
        "privacy_boundary": "Scheduled output is compact and sanitized; material notifications are sent through the retail order notification path.",
        "result_truncated": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Star safe retail-order refresh")
    parser.add_argument("--limit", type=int, default=20, help="maximum due orders to refresh")
    parser.add_argument("--no-notify", action="store_true", help="refresh/preview without Telegram notifications")
    parser.add_argument("--json", action="store_true", help="print compact JSON result")
    args = parser.parse_args(argv)

    tool = _load_tool_module()
    refresh_tool = getattr(tool, "retail_order_refresh_run_tool")
    result = json.loads(refresh_tool({"send_notifications": not args.no_notify, "limit": args.limit}))
    output = _compact_result(result)
    if args.json:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "retail order refresh: "
            f"due={output.get('due_orders_count', 0)} "
            f"refreshed={output.get('refreshed_count', 0)} "
            f"notifications_sent={output.get('notifications_sent', 0)}"
        )
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
