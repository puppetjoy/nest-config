"""Run retained Honcho contracts against real external-provider discovery, never core stubs."""
import importlib
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile

import pytest

STAGED = Path(os.environ.get('NEST_PLUGIN_STAGE', '.integration')).resolve()
_HOME = tempfile.TemporaryDirectory(prefix='nest-honcho-', dir=os.environ['TMPDIR'])
os.environ['HOME'] = _HOME.name
os.environ['HERMES_HOME'] = str(Path(_HOME.name) / 'profile')
plugins = Path(os.environ['HERMES_HOME']) / 'plugins'
plugins.mkdir(parents=True)
shutil.copytree(STAGED / 'honcho', plugins / 'honcho', ignore=shutil.ignore_patterns('.git', '__pycache__'))

from plugins.memory import find_provider_dir, import_provider_module
assert find_provider_dir('honcho') == plugins / 'honcho'
package = import_provider_module('honcho')
assert Path(package.__file__).resolve() == plugins / 'honcho/__init__.py'
# A stable test-only name replaces the old bundled import and patch targets. Every module
# comes from the package selected by real discovery; production needs no compatibility alias.
sys.modules['nest_honcho'] = package
for name in ('client', 'client_cache', 'config_schema', 'session', 'session_context', 'session_peers', 'session_auth',
             'session_migration', 'recall_sync', 'dialectic', 'cli', 'evaluation', 'identity_audit'):
    sys.modules['nest_honcho.' + name] = importlib.import_module(package.__name__ + '.' + name)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'profile'))


@pytest.fixture
def network_attempts():
    return []


@pytest.fixture(autouse=True)
def no_live_honcho_network(monkeypatch, network_attempts):
    def blocked(address, *args, **kwargs):
        network_attempts.append(address)
        raise RuntimeError('Network disabled in external Honcho regressions')
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket.socket, 'connect', lambda self, address: blocked(address))
    yield
    assert not network_attempts
