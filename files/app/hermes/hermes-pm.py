#!/usr/bin/python3.14
"""Nest's source-managed PM entry and Python compatibility launcher.

PM owns resolution, dependency selection and leases. This adapter never runs pip/uv,
never reads credentials and never persists a selected generation path.
"""
import os
from pathlib import Path
import runpy
import sys


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
    source = configure(install)
    import pm
    inputs = dependency_inputs(install)
    if check:
        return 0 if pm.venv_is_current(extras=['all'], plugins=inputs, project_root=source) else 1
    # This public PM operation owns the whole dependency union, including the
    # broker's buildable immutable source member and the external plugin manifests.
    pm.sync_venv(['all'], explicit=True, plugins=inputs, project_root=source)
    return 0


def launch(install, args):
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
    if operation in ('sync', 'check'):
        raise SystemExit(sync(install, check=operation == 'check'))
    if operation == 'python' and arguments:
        launch(install, arguments)
    else:
        raise SystemExit('Usage: hermes-pm {sync|check|python} INSTALL [PYTHON_ARGS...]')
