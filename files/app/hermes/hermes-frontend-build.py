#!/usr/bin/env python3
"""Build managed source frontends with the same PM toolchain and receipts as launch."""
import argparse
from pathlib import Path
import sys


def run(source, product, *, check=False):
    sys.path.insert(0, str(source))
    from hermes_cli.source_build import (
        build_source_tui, build_source_web, prepare_launch_dependencies,
        source_build_env, source_product_current,
    )
    output = source / ('ui-tui/dist' if product == 'tui' else 'hermes_cli/web_dist')
    if source_product_current(source, product, output):
        return 0
    if check:
        return 1
    env = source_build_env(explicit=True, verify=False)
    prepare_launch_dependencies(source, env=env)
    (build_source_tui if product == 'tui' else build_source_web)(source, env=env)
    if not source_product_current(source, product, output):
        raise RuntimeError('Managed frontend build did not produce a current receipt')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'build'))
    parser.add_argument('source', type=Path)
    parser.add_argument('product', choices=('tui', 'web'))
    args = parser.parse_args()
    sys.exit(run(args.source, args.product, check=args.action == 'check'))
