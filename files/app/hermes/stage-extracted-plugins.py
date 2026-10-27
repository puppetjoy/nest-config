#!/usr/bin/env python3
"""Stage immutable external inputs and apply Nest's reviewed patches; never install live."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SOURCES = {
    'honcho': ('https://github.com/plastic-labs/honcho.git', 'e2d2aba182862deeb846e5cd4a30a41bce0ed82a', 'hermes-plugin-honcho'),
    'camofox': ('https://github.com/NousResearch/hermes-official-plugins.git', '190593f4ce4c481a80ed27448535c867c5c6e27f', 'camofox'),
    'github-copilot': ('https://github.com/NousResearch/hermes-labs-plugins.git', '346cfe972f72b6a966e84c1004cf8742554b193d', 'github-copilot'),
}


def _stage(destination, patches):
    destination.mkdir(parents=True, exist_ok=True)
    identities = {}
    for name, (url, revision, subdir) in SOURCES.items():
        checkout = destination / (name + '-input.git')
        if not checkout.exists():
            subprocess.run(['git', 'init', '--bare', str(checkout)], check=True)
            subprocess.run(['git', '-C', str(checkout), 'fetch', '--depth', '1', url, revision], check=True)
        actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', revision + '^{commit}'], text=True).strip()
        if actual != revision:
            raise RuntimeError('Immutable input did not match: ' + name)
        tree = destination / name
        if tree.exists():
            raise RuntimeError('Refusing to overwrite staged tree: ' + str(tree))
        archive = subprocess.check_output(['git', '-C', str(checkout), 'archive', revision + ':' + subdir])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(tree, filter='data')
        patch = patches / (name + '.patch')
        if patch.exists() and patch.stat().st_size:
            # git apply in an ignored subdirectory of another worktree can
            # silently skip every path. Give this exported tree its own root.
            subprocess.run(['git', 'init', '--quiet', str(tree)], check=True)
            subprocess.run(['git', 'apply', '--check', '-p1', str(patch)], cwd=tree, check=True)
            subprocess.run(['git', 'apply', '-p1', str(patch)], cwd=tree, check=True)
            shutil.rmtree(tree / '.git')
        hashes = {str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(tree.rglob('*')) if p.is_file()}
        identities[name] = {'url': url, 'revision': revision, 'subdir': subdir, 'files': hashes,
                            'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest() if patch.exists() else None}
    (destination / 'sources.json').write_text(json.dumps(identities, indent=2) + '\n')


def stage(destination, patches):
    if destination.exists():
        identities = json.loads((destination / 'sources.json').read_text())
        for name, (url, revision, subdir) in SOURCES.items():
            row = identities[name]
            patch = patches / (name + '.patch')
            expected = hashlib.sha256(patch.read_bytes()).hexdigest()
            if (row['url'], row['revision'], row['subdir'], row['patch_sha256']) != (url, revision, subdir, expected):
                raise RuntimeError('Staged input changed: ' + name)
            for path, digest in row['files'].items():
                if hashlib.sha256((destination / name / path).read_bytes()).hexdigest() != digest:
                    raise RuntimeError('Staged bytes changed: ' + name + '/' + path)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Failed downloads or patches leave no partially publishable plugin trees.
    with tempfile.TemporaryDirectory(prefix='.plugins-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'ready'
        _stage(staged, patches)
        os.rename(staged, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--patches', type=Path, default=ROOT / 'files/app/hermes/extracted-plugins')
    args = parser.parse_args()
    stage(args.destination.resolve(), args.patches.resolve())
