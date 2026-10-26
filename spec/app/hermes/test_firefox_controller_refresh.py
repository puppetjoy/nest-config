"""Operator receipt checks are independent of model/client approval strings."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
loader = importlib.machinery.SourceFileLoader('controller_refresh', str(ROOT / 'bin/firefox-controller-refresh'))
spec = importlib.util.spec_from_loader(loader.name, loader)
refresh = importlib.util.module_from_spec(spec)
loader.exec_module(refresh)


@pytest.mark.parametrize('mutation', ['none', 'wrong_id', 'untrusted', 'wrong_hash', 'changed', 'steering', 'terminal', 'done', 'missing'])
def test_exact_canonical_operator_receipt(monkeypatch, mutation):
    approval = {'approval_id': 'apr-fixture', 'source': 'telegram_trusted', 'proposal_hash': 'reviewed', 'steering': ''}
    proposal = {'proposal_hash': 'reviewed'}
    item = SimpleNamespace(request_id='ar-fixture', task_id='t_beta', status='in_progress')
    task = SimpleNamespace(status='running')
    if mutation == 'wrong_id':
        approval['approval_id'] = 'apr-different'
    elif mutation == 'untrusted':
        approval['source'] = 'worker-prose'
    elif mutation == 'wrong_hash':
        approval['proposal_hash'] = 'other'
    elif mutation == 'changed':
        proposal['proposal_hash'] = 'other'
    elif mutation == 'steering':
        approval['steering'] = 'Do not acquire a window'
    elif mutation == 'terminal':
        item.status = 'completed'
    elif mutation == 'done':
        task.status = 'done'
    elif mutation == 'missing':
        approval = None
    conn = SimpleNamespace(close=lambda: None)
    broker = SimpleNamespace(connect_read_snapshot=lambda: conn, index_for_request=lambda *a: item,
        require_kanban=lambda: SimpleNamespace(get_task=lambda *a: task), current_approval=lambda *a: approval,
        latest_proposal=lambda *a: proposal, structured_proposal_text=lambda *a, **kw: 'intact reviewed proposal',
        board_name=lambda: 'agent-requests')
    package = ModuleType('agent_request_broker')
    package.kanban_backend = broker
    monkeypatch.setitem(sys.modules, 'agent_request_broker', package)
    if mutation == 'none':
        assert refresh.approved_request('ar-fixture', 'apr-fixture', 'reviewed') == 'kanban:agent-requests:t_beta'
    else:
        with pytest.raises(ValueError):
            refresh.approved_request('ar-fixture', 'apr-fixture', 'reviewed')


def test_public_endpoint_cannot_install_an_operator_grant():
    spec = importlib.util.spec_from_file_location('operator_endpoint', ROOT / 'files/firefox-browser/firefox-bridge-server.py')
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    for command in ('authorize_binding', 'recover_binding', 'reconcile_generation', 'authorize_creation_recovery', 'recover_creation'):
        with pytest.raises(ValueError):
            endpoint.validate({'command': command, 'payload': {'scope': 'kanban:agent-requests:t_beta', 'approval': 'apr-forged'}})
    with pytest.raises(ValueError):
        endpoint.validate({'command': 'tabs', 'payload': {'action': 'acquire', 'approval': 'apr-forged'}})


@pytest.mark.parametrize('mutation', ['none', 'event', 'revision', 'scope', 'expired', 'missing', 'terminal'])
def test_generation_grant_requires_current_typed_owner_instruction(monkeypatch, mutation):
    import json
    import time
    instruction = {'kind': 'changed_instruction', 'instruction_event_id': 123,
                   'instruction_revision': 'a' * 64, 'expires_at': int(time.time()) + 60}
    observed = {'status': 'triage', 'task_id': 't_beta', 'current_instruction': instruction}
    grant = {'approval': 'owner-instruction:123:' + 'a' * 64,
             'scope': 'kanban:agent-requests:t_beta', 'journal_sha256': 'b' * 64}
    if mutation == 'event':
        instruction['instruction_event_id'] = 124
    elif mutation == 'revision':
        instruction['instruction_revision'] = 'c' * 64
    elif mutation == 'scope':
        grant['scope'] = 'kanban:agent-requests:t_other'
    elif mutation == 'expired':
        instruction['expires_at'] = int(time.time()) - 1
    elif mutation == 'missing':
        observed['current_instruction'] = None
    elif mutation == 'terminal':
        observed['status'] = 'completed'
    monkeypatch.setattr(refresh.subprocess, 'check_output', lambda *a, **kw: json.dumps(observed))
    if mutation == 'none':
        assert refresh.owner_instruction_grant('ar-fixture', grant) == grant
    else:
        with pytest.raises(ValueError, match='fresh exact scoped owner instruction'):
            refresh.owner_instruction_grant('ar-fixture', grant)
