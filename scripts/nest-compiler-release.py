#!/usr/bin/env python3
"""Produce a compiler projection from checked executor inputs, never live r10k."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

INPUT_SCRIPT = Path(__file__).with_name('nest-executor-inputs.py')
spec = importlib.util.spec_from_file_location('executor_inputs', INPUT_SCRIPT)
assert spec is not None and spec.loader is not None
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


def require(value):
    if not value:
        raise ValueError('Compiler release production unavailable')


def copy(source, target):
    """Copy without Git metadata or following links; no shared input inodes."""
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode):
        link = os.readlink(source)
        require(not link.startswith('/'))
        target.symlink_to(link)
    elif stat.S_ISDIR(info.st_mode):
        target.mkdir(mode=0o700)
        for child in sorted(source.iterdir()):
            if child.name != '.git':
                copy(child, target / child.name)
        target.chmod(stat.S_IMODE(info.st_mode))
    else:
        require(stat.S_ISREG(info.st_mode))
        with source.open('rb') as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer)
        target.chmod(stat.S_IMODE(info.st_mode))


def checked_inputs(project, source, base):
    expected = inputs.canonical(inputs.observe(project, source, base))
    receipt = project / '.executor-inputs.json'
    require(not receipt.is_symlink() and receipt.read_bytes() == expected)
    return expected


def produce(project, destination, source, base):
    # Call only in an immutable digest image, with no input overlays or writer.
    # Rechecking input identity detects ordinary drift, not concurrent attacks.
    project = project.resolve(strict=True)
    parent = destination.parent
    require(destination.is_absolute() and parent.resolve(strict=True) == parent)
    info = parent.stat()
    require(info.st_uid == os.geteuid() and not info.st_mode & 0o022)
    require(destination.name not in ('', '.', '..'))
    require(destination != project and project not in destination.parents and destination not in project.parents)
    original = checked_inputs(project, source, base)
    # Exclusive allocation: failure preserves diagnostics and refuses retries.
    destination.mkdir(mode=0o700)
    root = destination / 'main'
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    (root / 'manifests').mkdir(mode=0o755)
    (root / 'manifests').chmod(0o755)
    copy(project / 'site.pp', root / 'manifests/site.pp')
    copy(project / 'hiera.yaml', root / 'hiera.yaml')
    (root / 'data').mkdir(mode=0o755)
    (root / 'data').chmod(0o755)
    # The control SHA binds only tracked input paths. Never admit ignored or
    # untracked files from the build workspace into the compiler projection.
    data_files = inputs.git(project, 'ls-files', '-z', '--', 'data').split('\0')
    for name in filter(None, data_files):
        path = Path(name)
        require(path.parts[0] == 'data' and '..' not in path.parts)
        target = root / path
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        directory = target.parent
        while directory != root:
            directory.chmod(0o755)
            directory = directory.parent
        copy(project / path, target)
    copy(project / '.modules', root / '.modules')
    # Nest is also a control repo. Its module-level private Hiera link points
    # into a nested Bolt installation that does not exist in installed modules.
    # Relocate that one known link to the accepted sibling private module.
    private_data = root / '.modules/nest/data/private'
    require(private_data.is_symlink() and os.readlink(private_data) == '../.modules/private/data')
    private_data.unlink()
    private_data.symlink_to('../../private/data')
    # Bolt fixtures are not compiler inputs; their links point outside installed
    # module data. Keep the explicit existing served-Nest spec pruning boundary.
    nest_spec = root / '.modules/nest/spec'
    require(nest_spec.is_dir() and not nest_spec.is_symlink())
    shutil.rmtree(nest_spec)
    config = 'modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo ' + source + '\n'
    (root / 'environment.conf').write_text(config, encoding='ascii')
    (root / 'environment.conf').chmod(0o644)
    require(checked_inputs(project, source, base) == original)
    # One shared inventory implementation defines the native hook identity.
    ruby = '''require ARGV.shift
root, source = ARGV
rows = NestPuppetVersionedCode.inventory(root)
NestPuppetVersionedCode.check(rows.none? { |r| r[1] == 'link' && r[2].start_with?('/') })
expected = { 'schema' => 1, 'environment' => 'main', 'source' => source,
             'code_id' => NestPuppetVersionedCode.code_id(rows) }
NestPuppetVersionedCode::Snapshot.new(root, expected, readonly: ->(_path) { true })
puts JSON.generate(expected)
'''
    helper = Path(__file__).resolve().parents[1] / 'files/puppet-versioned-code.rb'
    result = subprocess.run(['ruby', '-e', ruby, str(helper), str(root), source],
                            check=True, capture_output=True, text=True, timeout=180)
    expected = json.loads(result.stdout)
    require(set(expected) == {'schema', 'environment', 'source', 'code_id'} and expected['source'] == source)
    # Private projection contains private module data. Only these two small
    # identity files are eligible for public CI artifact publication.
    for name, payload in [('executor-inputs.json', original), ('expected.json', inputs.canonical(expected))]:
        with (destination / name).open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('/opt/nest'))
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(produce(args.project, args.destination, args.source, args.base), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Compiler release production unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
