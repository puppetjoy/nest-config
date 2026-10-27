"""Real profile-local discovery and scoped credentials on the exact externalized core."""
import importlib
import json
import os
from pathlib import Path
import sys

import pytest

STAGED = Path(os.environ['NEST_PLUGIN_STAGE']).resolve()
INSTALL = Path(os.environ['NEST_PM_INSTALL']).resolve()


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    home = tmp_path / '.hermes/profiles/quill'
    home.mkdir(parents=True)
    monkeypatch.setenv('HERMES_HOME', str(home))
    for key in ('COPILOT_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    plugins = home / 'plugins'
    plugins.mkdir()
    for name in ('honcho', 'camofox', 'github-copilot'):
        (plugins / name).symlink_to(STAGED / name, target_is_directory=True)
    (plugins / 'nest-agent-request-broker').symlink_to(INSTALL / 'agent-request-broker', target_is_directory=True)
    (home / 'config.yaml').write_text('memory:\n  provider: honcho\nplugins:\n  enabled: [camofox, nest-agent-request-broker]\n')
    return home


def test_external_memory_provider_discovery(profile):
    from plugins.memory import find_provider_dir, import_provider_module
    assert find_provider_dir('honcho') == profile / 'plugins/honcho'
    package = import_provider_module('honcho')
    assert Path(package.__file__).resolve() == STAGED / 'honcho/__init__.py'
    assert package.HonchoMemoryProvider().name == 'honcho'
    assert import_provider_module('honcho', 'evaluation').SAFE_PROBE_INPUT_CONTRACT
    assert callable(import_provider_module('honcho', 'identity_audit').audit_peer_card_identity_relations)


def test_camofox_real_plugin_manager_loads_browser_ids(profile):
    from hermes_cli.plugins import PluginManager
    manager = PluginManager()
    manager.discover_and_load()
    plugin = manager._plugins['camofox']
    assert plugin.error is None
    assert plugin.enabled
    assert Path(plugin.module.__file__).resolve() == STAGED / 'camofox/__init__.py'
    assert {'browser_navigate', 'browser_vision', 'browser_console', 'browser_snapshot'} <= set(plugin.tools_registered)
    broker = manager._plugins['nest-agent-request-broker']
    assert broker.enabled and broker.error is None
    assert broker.tools_registered == []
    from pm.plugins_state import enabled_plugins_ordered
    assert 'nest-agent-request-broker' in enabled_plugins_ordered()[profile / 'plugins']


def test_copilot_real_provider_discovery_and_employer_scope(profile, monkeypatch):
    import providers
    from agent.secret_scope import (set_secret_scope, reset_secret_scope, set_multiplex_context, reset_multiplex_context)
    copilot = providers.get_provider_profile('copilot')
    assert copilot is not None
    assert providers.provider_source('copilot') == 'user'
    assert providers.get_provider_profile('github-copilot') is copilot
    assert providers.get_provider_profile('copilot-acp') is not None
    credentials = importlib.import_module(type(copilot).__module__ + '.credentials')
    monkeypatch.setenv('GH_TOKEN', 'ghu_personal_fixture_not_a_credential')
    monkeypatch.setenv('GITHUB_TOKEN', 'ghu_personal_fixture_not_a_credential')
    scope = set_secret_scope({'COPILOT_GITHUB_TOKEN': 'ghu_employer_fixture_not_a_credential'}, profile_home=str(profile))
    multiplex = set_multiplex_context(True)
    try:
        assert credentials.resolve_copilot_token() == ('ghu_employer_fixture_not_a_credential', 'COPILOT_GITHUB_TOKEN')
        reset_secret_scope(scope)
        scope = set_secret_scope({}, profile_home=str(profile))
        assert credentials.resolve_copilot_token() == ('', '')
    finally:
        reset_secret_scope(scope)
        reset_multiplex_context(multiplex)
