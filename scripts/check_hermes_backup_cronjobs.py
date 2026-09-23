#!/usr/bin/env python3
"""Validate rendered Hermes backup CronJobs use one unscoped generation plan.

Pass one or more rendered KubeCM YAML files, for example:
  scripts/check_hermes_backup_cronjobs.py render/talon.yaml render/star.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FORBIDDEN_ARG_RE = re.compile(r"^-\s+['\"]?(namespace|service)=", re.MULTILINE)


def cronjob_block(text: str, service: str) -> str:
    match = re.search(rf"(?m)^\s*name:\s*{re.escape(service)}-backup\s*$", text)
    if not match:
        raise AssertionError(f"{service}: rendered manifest does not contain {service}-backup CronJob")

    start = match.start()
    next_doc = text.find("\n---", start + 1)
    if next_doc == -1:
        return text[start:]
    return text[start:next_doc]


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    services = [
        service
        for service in ("talon", "star", "beryl", "quill")
        if f"name: {service}-backup" in text
    ]
    if not services:
        raise AssertionError(f"{path}: no Hermes profile backup CronJob found")

    checked: list[str] = []
    for service in services:
        block = cronjob_block(text, service)
        if "nest::app::hermes::backup" not in block:
            raise AssertionError(f"{path}: {service}-backup does not call nest::app::hermes::backup")
        if re.search(r"^-\s+['\"]?(profile|service_name)=", block, re.MULTILINE):
            raise AssertionError(f"{path}: {service}-backup labels a full-home backup by profile")
        forbidden = FORBIDDEN_ARG_RE.search(block)
        if forbidden:
            raise AssertionError(
                f"{path}: {service}-backup still passes forbidden Hermes backup arg "
                f"{forbidden.group(1)}="
            )
        checked.append(service)
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rendered_yaml", nargs="+", type=Path)
    args = parser.parse_args()

    seen: set[str] = set()
    for path in args.rendered_yaml:
        seen.update(check_file(path))

    if not seen:
        raise AssertionError("no rendered Hermes backup CronJobs were checked")

    print("Hermes backup CronJobs use one unscoped full-home generation plan")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
