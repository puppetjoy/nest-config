#!/usr/bin/env python3
"""Publish externally owned Hermes identity from its verified source checkout."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('branch')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = args.source.resolve()
    sys.path.insert(0, str(root))
    from hermes_cli.version_info import _git_version_info
    from scripts.write_install_stamp import build_stamp, write_stamp

    info = _git_version_info(root)
    if not info.commit or info.base_version == 'unknown':
        parser.error('verified source commit and reachable release metadata required')
    values: dict[str, Any] = dict(
        update_mechanism='external',
        commit=info.commit,
        commit_date=info.commit_date,
        branch=args.branch,
        base_version=info.base_version,
        display_version=info.derived_version,
        distance=info.distance,
        dirty=info.dirty,
        source='git',
    )
    output = root / 'install-stamp.json'
    if args.check:
        try:
            actual = json.loads(output.read_text())
        except (OSError, ValueError):
            return 1
        expected = build_stamp(**values)
        # Build time is receipt metadata, not a reason to rewrite an identity.
        return int(any(actual.get(key) != value for key, value in expected.items()
                       if key != 'builtAt'))
    write_stamp(output, **values)
    return 0


if __name__ == '__main__':
    sys.exit(main())
