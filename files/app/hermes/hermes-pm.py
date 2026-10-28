#!/usr/bin/python3.14
"""Nest's source-managed PM entry and Python compatibility launcher.

PM owns resolution, dependency selection and leases. This adapter never runs pip/uv,
never reads credentials and never persists a selected generation path.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

# Safe activation floors survive ordinary fast-forward nest/main updates. The
# broker must contain both compatibility and the newer installed hardening.
CHECKPOINTS = {
    'src': ('6854ac37123350da8da84291b37b12116a25e46b',),
    'agent-request-broker': ('5c6dbe92560a1240e8f61c9a12cbdaaa0eba0079',
                             '8fb0efaf46333d572674609195a78decbd7ee162'),
}


def source_state(install):
    state = {}
    for name, checkpoints in CHECKPOINTS.items():
        repo = install / name
        # Puppet owns these checkouts as root; PM runs as the Nest user. Trust
        # only this explicit managed directory for these read-only Git calls.
        command = ['git', '-c', 'safe.directory=' + str(repo), '-C', str(repo)]
        def git(*args):
            return subprocess.check_output([*command, *args])
        head = git('rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
        for checkpoint in checkpoints:
            if subprocess.run([*command, 'merge-base', '--is-ancestor', checkpoint, head],
                              capture_output=True).returncode:
                raise RuntimeError('PM safe checkpoint missing from ' + name + ': ' + checkpoint)
        # Puppet deliberately overlays tracked adapters. Bind their actual bytes
        # too, without rejecting those managed differences as a dirty checkout.
        digest = hashlib.sha256()
        for path in sorted(git('ls-files', '-z').split(b'\0')):
            if path:
                file = repo / os.fsdecode(path)
                digest.update(path + b'\0')
                digest.update(file.read_bytes() if file.exists() else b'<absent>')
        state[name] = {'head': head, 'content': digest.hexdigest()}
    return state


def receipt_path(install):
    return install / 'tools' / 'nest-source-state.json'


def verified_receipt(install, state):
    try:
        return json.loads(receipt_path(install).read_text()) == state
    except (OSError, ValueError):
        return False


def configure(install):
    source = install / 'src'
    os.environ['HERMES_RUNTIME_DIR'] = str(install / 'tools')
    sys.path.insert(0, str(source))
    return source


def dependency_inputs(install):
    from pm.plugin_inputs import Candidates
    assets = install / 'extracted-plugins'
    return Candidates([assets / name for name in ('honcho', 'camofox', 'github-copilot')]
                      + [install / 'agent-request-broker'])


def sync(install, *, check=False):
    before = source_state(install)
    source = configure(install)
    import pm
    inputs = dependency_inputs(install)
    if check:
        return 0 if (verified_receipt(install, before)
                     and pm.venv_is_current(extras=['all'], plugins=inputs, project_root=source)
                     and source_state(install) == before) else 1
    # This public PM operation owns the whole dependency union, including the
    # broker's buildable immutable source member and the external plugin manifests.
    pm.sync_venv(['all'], explicit=True, plugins=inputs, project_root=source)
    if source_state(install) != before:
        raise RuntimeError('Managed source changed during PM sync; wrappers must not activate')
    receipt = receipt_path(install)
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(before, sort_keys=True) + '\n')
    os.replace(temporary, receipt)
    return 0


def launch(install, args):
    if not verified_receipt(install, source_state(install)):
        raise RuntimeError('Managed source has no exact successful PM sync receipt')
    source = configure(install)
    from hermes_cli._launchers import resolve_store_python, runtime_command
    python = resolve_store_python(source)
    if python is None:
        raise RuntimeError('Managed interpreter is missing; apply the gated PM install first')
    # Keep the old Python-shaped consumers (services, config helpers, build state)
    # without pinning a venv or bypassing hermes_bootstrap activation and leases.
    entry = (
        'import runpy, sys; '
        f'sys.path.insert(1, {str(install / "agent-request-broker/src")!r}); '
        'args = sys.argv[1:]; '
        'sys.argv = args[1:] if args[:1] == ["-m"] else (["-c", *args[2:]] if args[:1] == ["-c"] else args); '
        'runpy.run_module(args[1], run_name="__main__", alter_sys=True) if args[:1] == ["-m"] else '
        '(exec(args[1], {"__name__": "__main__"}) if args[:1] == ["-c"] else runpy.run_path(args[0], run_name="__main__"))'
    )
    command = runtime_command(source, args, code=entry, python=python)
    os.execv(command[0], command)


if __name__ == '__main__':
    operation, directory, *arguments = sys.argv[1:]
    install = Path(directory).resolve()
    if operation == 'verify':
        print(json.dumps(source_state(install), sort_keys=True))
        raise SystemExit(0)
    if operation in ('sync', 'check'):
        raise SystemExit(sync(install, check=operation == 'check'))
    if operation == 'python' and arguments:
        launch(install, arguments)
    else:
        raise SystemExit('Usage: hermes-pm {verify|sync|check|python} INSTALL [PYTHON_ARGS...]')
