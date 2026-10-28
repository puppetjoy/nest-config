#!/usr/bin/env python3
"""Manage glab policy/auth while preserving its runtime version receipt."""

import argparse
import os
from pathlib import Path
import sys

try:
    import hermes_yaml as yaml
except ImportError:
    import yaml


def reconcile(current, managed):
    desired = dict(managed)
    # glab persists this field even with check_update disabled. It is not
    # authentication or gateway configuration and must not cause refreshes.
    if 'last_seen_version' in current:
        desired['last_seen_version'] = current['last_seen_version']
    return desired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'apply'))
    parser.add_argument('config', type=Path)
    parser.add_argument('managed', type=Path)
    args = parser.parse_args()
    try:
        current = yaml.safe_load(args.config.read_text()) or {}
        managed = yaml.safe_load(args.managed.read_text()) or {}
        desired = reconcile(current, managed)
        if current == desired:
            return 0
        if args.action == 'check':
            return 1
        # Never expose credential-bearing YAML in logs or a world-readable file.
        temporary = args.config.with_name(args.config.name + '.puppet-new')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            yaml.safe_dump(desired, stream, sort_keys=False)
        temporary.replace(args.config)
        return 0
    except (OSError, ValueError, yaml.YAMLError):
        print('Unable to reconcile managed glab configuration', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
