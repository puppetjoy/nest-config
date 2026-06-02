#!/usr/bin/env python3
import sys
from pathlib import Path
import yaml


def load_yaml(path):
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text())
    return data if isinstance(data, dict) else {}


def merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict):
            current = dst.get(key)
            if not isinstance(current, dict):
                current = {}
                dst[key] = current
            merge(current, value)
        else:
            dst[key] = value


def matches(dst, src):
    for key, value in src.items():
        if isinstance(value, dict):
            current = dst.get(key)
            if not isinstance(current, dict):
                return False
            if not matches(current, value):
                return False
        elif dst.get(key) != value:
            return False
    return True


def main(argv):
    if len(argv) != 4 or argv[1] not in {'check', 'apply'}:
        print('usage: manage-config.py check|apply CONFIG_PATH MANAGED_CONFIG_PATH', file=sys.stderr)
        return 64
    mode, config_path, managed_path = argv[1:]
    config = load_yaml(config_path)
    managed = load_yaml(managed_path)
    if mode == 'check':
        return 0 if matches(config, managed) else 1
    merge(config, managed)
    p = Path(config_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(config, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
