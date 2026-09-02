#!/usr/bin/env python3
"""Converge a Hermes .env while retaining explicitly runtime-owned keys."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path

ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        match = ASSIGNMENT.match(raw_line.strip())
        if not match:
            continue
        key, serialized_value = match.groups()
        if key in values:
            raise ValueError(f"duplicate environment key in {path}: {key}")
        values[key] = serialized_value
    return values


def expected_content(base: Path, target: Path, preserved_keys: list[str]) -> str:
    base_content = base.read_text(encoding="utf-8-sig").rstrip("\n")
    base_values = assignments(base)
    target_values = assignments(target)

    overlap = sorted(set(preserved_keys) & set(base_values))
    if overlap:
        raise ValueError(f"runtime-owned key is also administrator-managed: {', '.join(overlap)}")

    lines = [base_content] if base_content else []
    lines.extend(f"{key}={target_values[key]}" for key in preserved_keys if key in target_values)
    return "\n".join(lines) + "\n"


def target_matches(target: Path, expected: str) -> bool:
    if not target.exists() or not target.is_file():
        return False
    return target.read_text(encoding="utf-8") == expected and (target.stat().st_mode & 0o777) == 0o600


def atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "sync"))
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--preserve", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected = expected_content(args.base, args.target, args.preserve)
    if args.mode == "check":
        return 0 if target_matches(args.target, expected) else 1
    if not target_matches(args.target, expected):
        atomic_write(args.target, expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
