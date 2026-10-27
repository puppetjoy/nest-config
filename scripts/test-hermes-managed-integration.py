#!/usr/bin/env python3
"""Reproduce the source-only Hermes PM/plugin acceptance in an empty local workspace.

No live profiles, installs, credentials, Git refs or services are changed. All source
inputs are exported at immutable commits; PM owns every Python dependency change.
"""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = '085f562af53a6fedadac3681e2c498fc71316132'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export(repo, revision, destination):
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', revision + '^{commit}'], text=True).strip()
    if actual != revision or len(revision) != 40:
        raise ValueError('Expected a full immutable source revision')
    archive = subprocess.check_output(['git', '-C', str(repo), 'archive', revision])
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(destination, filter='data')


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-repo', required=True, type=Path)
    parser.add_argument('--broker-repo', required=True, type=Path)
    parser.add_argument('--broker-sha', required=True)
    parser.add_argument('--work', required=True, type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    # Never turn a source-only test into an existing installation repair.
    if work.exists():
        raise ValueError('Use a new empty --work path, not an existing install')
    work.mkdir(parents=True)
    install = work / 'install'
    install.mkdir()
    home = work / 'home'
    home.mkdir()
    scratch = work / 'scratch'
    scratch.mkdir()
    # Remove ambient profile/session/provider context before importing the exact core.
    for key in list(os.environ):
        if key.startswith(('HERMES_', 'AGENT_REQUEST_')) or key.endswith(('_TOKEN', '_API_KEY', '_SECRET', '_PASSWORD', '_CREDENTIALS')):
            os.environ.pop(key, None)
    os.environ.update(HOME=str(home), HERMES_HOME=str(install), TMPDIR=str(scratch), TMP=str(scratch),
                      TEMP=str(scratch), PYTHONDONTWRITEBYTECODE='1')
    export(args.core_repo, CORE_SHA, install / 'src')
    export(args.broker_repo, args.broker_sha, install / 'agent-request-broker')
    broker = install / 'agent-request-broker'
    (broker / 'plugin.yaml').write_text("name: nest-agent-request-broker\nversion: '1.0'\ndescription: Nest Agent Request broker runtime package\n")
    (broker / '__init__.py').write_text('def register(ctx):\n    pass\n')
    (install / 'config.yaml').write_text('memory:\n  provider: default\nplugins:\n  enabled: []\n')
    stage = work / 'plugins'
    staging = load('nest_staging', ROOT / 'files/app/hermes/stage-extracted-plugins.py')
    staging.stage(stage, ROOT / 'files/app/hermes/extracted-plugins')
    staging.stage(stage, ROOT / 'files/app/hermes/extracted-plugins')  # idempotent verification
    (install / 'extracted-plugins').symlink_to(stage, target_is_directory=True)
    helper = ROOT / 'files/app/hermes/hermes-pm.py'
    manager = load('nest_pm', helper)
    source = manager.configure(install)
    import pm
    # First exercise exactly the production extras/members, with no test dependency.
    assert manager.sync(install) == 0
    assert manager.sync(install, check=True) == 0
    # Test-only member: no pytest or test mutation enters the production manifest.
    tests = work / 'test-dependencies'
    tests.mkdir()
    (tests / 'pyproject.toml').write_text('[project]\nname="nest-hermes-contract-tests"\nversion="1.0"\ndependencies=["pytest==9.1.1"]\n')
    from pm.plugin_inputs import Candidates
    members = manager.dependency_inputs(install)
    pm.sync_venv(['all'], explicit=True, plugins=Candidates([*members.dirs, tests]), project_root=source)
    os.environ.update(NEST_PLUGIN_STAGE=str(stage), NEST_PM_INSTALL=str(install))
    groups = {
        'honcho': [ROOT / 'spec/files/extracted_plugins/honcho'],
        'camofox': [stage / 'camofox/tests'],
        'copilot': [stage / 'github-copilot/tests'],
        'runtime-discovery': [ROOT / 'spec/files/extracted_plugins/test_pm_runtime.py',
                              ROOT / 'spec/files/extracted_plugins/test_external_discovery.py'],
    }
    results = {'core': CORE_SHA, 'broker': args.broker_sha, 'groups': {}}
    failed = False
    for name, paths in groups.items():
        report = work / (name + '.xml')
        command = [sys.executable, '-I', str(helper), 'python', str(install), '-m', 'pytest', '-q',
                   '--junitxml=' + str(report), *map(str, paths)]
        with (work / (name + '.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        tree = ET.parse(report)
        cases = tree.findall('.//testcase')
        row = {'tests': len(cases), 'failures': len(tree.findall('.//failure')),
               'errors': len(tree.findall('.//error')), 'skipped': len(tree.findall('.//skipped')),
               'exit_code': result.returncode}
        results['groups'][name] = row
        failed |= bool(result.returncode or row['failures'] or row['errors'] or row['skipped'])
        print(name + ': ' + json.dumps(row), flush=True)
    (work / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
