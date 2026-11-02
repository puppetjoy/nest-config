#!/usr/bin/env python3
"""Reproduce the source-only Hermes PM/plugin acceptance in an empty local workspace.

No live profiles, installs, credentials, Git refs or services are changed. All source
inputs are exported at immutable commits; PM owns every Python dependency change.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = '6854ac37123350da8da84291b37b12116a25e46b'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export(repo, revision, destination):
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', revision + '^{commit}'], text=True).strip()
    if actual != revision or len(revision) != 40:
        raise ValueError('Expected a full immutable source revision')
    subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(repo), str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'checkout', '--detach', revision], check=True)


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-repo', required=True, type=Path)
    parser.add_argument('--core-sha', default=CORE_SHA)
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
    export(args.core_repo, args.core_sha, install / 'src')
    export(args.broker_repo, args.broker_sha, install / 'agent-request-broker')
    broker = install / 'agent-request-broker'
    (broker / 'plugin.yaml').write_text("name: nest-agent-request-broker\nversion: '1.0'\ndescription: Nest Agent Request broker runtime package\n")
    (broker / '__init__.py').write_text('from agent_request_broker.blocked_writer_plugin import register\n')
    (install / 'config.yaml').write_text('memory:\n  provider: default\nplugins:\n  enabled: []\n')
    stage = work / 'plugins'
    staging = load('nest_staging', ROOT / 'files/app/hermes/stage-extracted-plugins.py')
    staging.stage(stage, ROOT / 'files/app/hermes/extracted-plugins')
    staging.stage(stage, ROOT / 'files/app/hermes/extracted-plugins')  # idempotent verification
    (install / 'extracted-plugins').symlink_to(stage, target_is_directory=True)
    helper = ROOT / 'files/app/hermes/hermes-pm.py'
    manager = load('nest_pm', helper)
    refusals = {}
    for name, unsafe, restored in [
        ('src', '04fe62345b00986e6a1f4d4776296f7c1e82e1ce', args.core_sha),
        ('agent-request-broker', '5c6dbe92560a1240e8f61c9a12cbdaaa0eba0079', args.broker_sha),
    ]:
        repo = install / name
        subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', unsafe], check=True)
        refusal = subprocess.run([sys.executable, '-I', str(helper), 'sync', str(install)],
                                 text=True, capture_output=True)
        assert refusal.returncode != 0 and 'safe checkpoint missing' in refusal.stderr, refusal.stderr
        assert not manager.receipt_path(install).exists()
        refusals[name] = {'rejected': unsafe, 'exit_code': refusal.returncode}
        subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', restored], check=True)
    (install / 'src/tools/agent_request_tool.py').symlink_to(
        broker / 'src/tools/agent_request_tool.py')
    source = manager.configure(install)
    import pm
    # First exercise exactly the production extras/members, with no test dependency.
    assert manager.sync(install) == 0
    assert manager.sync(install, check=True) == 0
    # Test-only member: no pytest or test mutation enters the production manifest.
    tests = work / 'test-dependencies'
    tests.mkdir()
    (tests / 'pyproject.toml').write_text('[project]\nname="nest-hermes-contract-tests"\nversion="1.0"\ndependencies=["pytest==9.1.1", "pytest-xdist"]\n')
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
    results = {'core': args.core_sha, 'broker': args.broker_sha, 'activation_refusals': refusals, 'groups': {}}
    workers = max(1, (getattr(os, 'process_cpu_count', os.cpu_count)() or os.cpu_count() or 1))
    results['workers'] = workers
    failed = False
    for name, paths in groups.items():
        report = work / (name + '.xml')
        command = [sys.executable, '-I', str(helper), 'python', str(install), '-m', 'pytest', '-vv', '-n', str(workers), '--max-worker-restart=0',
                   '--junitxml=' + str(report), *map(str, paths)]
        with (work / (name + '.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        startup = [line for line in (work / (name + '.log')).read_text().splitlines()
                   if 'created:' in line and 'workers' in line]
        observed_workers = any(f'created: {workers}/{workers} workers' in line for line in startup)
        tree = ET.parse(report)
        cases = tree.findall('.//testcase')
        row = {'tests': len(cases), 'failures': len(tree.findall('.//failure')),
               'errors': len(tree.findall('.//error')), 'skipped': len(tree.findall('.//skipped')),
               'exit_code': result.returncode, 'worker_startup': startup,
               'observed_workers': observed_workers,
               'case_ids': [(c.get('classname'), c.get('name')) for c in cases]}
        results['groups'][name] = row
        failed |= bool(result.returncode or row['failures'] or row['errors'] or row['skipped']
                       or not observed_workers or not cases
                       or len(row['case_ids']) != len(set(row['case_ids'])))
        print(name + ': ' + json.dumps(row), flush=True)
    # Advance real local rolling branches after the exact-source plugin tests.
    # No source refs in either input repository are changed.
    for name, branch in [('src', 'nest'), ('agent-request-broker', 'main')]:
        repo = install / name
        subprocess.run(['git', '-C', str(repo), 'checkout', '-B', branch], check=True)
        manifest = repo / 'pyproject.toml'
        manifest.write_text(manifest.read_text() + '\n# Local rolling convergence probe\n')
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c',
                        'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-am',
                        'Local rolling convergence probe'], check=True)
    command = [sys.executable, '-I', str(helper)]
    assert subprocess.run([*command, 'check', str(install)]).returncode != 0
    subprocess.run([*command, 'sync', str(install)], check=True)
    subprocess.run([*command, 'check', str(install)], check=True)
    subprocess.run([*command, 'python', str(install), '-c',
                    'import agent_request_broker.kanban_backend, honcho; print("Rolling PM imports passed")'], check=True)
    results['rolling_convergence'] = manager.source_state(install)
    # The supported named profile belongs to the installation-owning data root
    profile = install / 'profiles/talon'
    profile.mkdir(parents=True)
    (profile / 'config.yaml').write_text(
        'memory:\n  provider: default\nplugins:\n  enabled:\n    - agent-request-blocked-writer\n')
    shared = work / 'registration-board'
    shared.mkdir()
    probe_env = dict(os.environ, HERMES_HOME=str(profile), HERMES_PROFILE='talon',
                     HERMES_KANBAN_HOME=str(shared))
    probe = subprocess.run(
        [*command, 'python', str(install), str(ROOT / 'scripts/test-hermes-managed-registration.py'),
         str(work), str(install), str(profile), str(shared)],
        env=probe_env, text=True, capture_output=True, timeout=120)
    (work / 'registration.stdout').write_text(probe.stdout)
    (work / 'registration.stderr').write_text(probe.stderr)
    results['registration_exit_code'] = probe.returncode
    if probe.returncode:
        failed = True
    else:
        results['registration'] = json.loads(probe.stdout)
    (work / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
