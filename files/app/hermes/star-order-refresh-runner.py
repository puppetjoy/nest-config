#!/opt/hermes-agent/venv/bin/python
"""Run Star's safe shopping-order refresh loop.

This small systemd-friendly wrapper calls the secure_browser tool substrate in
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Star safe shopping-order refresh")
    parser.add_argument("--limit", type=int, default=20, help="maximum due orders to refresh")
    parser.add_argument("--no-notify", action="store_true", help="refresh/preview without Telegram notifications")
    parser.add_argument("--json", action="store_true", help="print compact JSON result")
    args = parser.parse_args(argv)

    tool = _load_tool_module()
    refresh_tool = getattr(tool, "secure_browser_order_refresh_run_tool")
    result = json.loads(refresh_tool({"send_notifications": not args.no_notify, "limit": args.limit}))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "secure browser order refresh: "
            f"due={len(result.get('plan', {}).get('due_orders', []))} "
            f"refreshed={len(result.get('refreshed', []))} "
            f"notifications_sent={result.get('notifications_sent', 0)}"
        )
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
