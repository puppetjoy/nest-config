"""Paired real Native hold -> trusted fixture callback -> public Nest helper.

Requires explicitly pinned Broker/Native sources; never uses production boards.
External kubectl is a transport double. All consent rows are genuine producers.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

BROKER = Path(os.environ['NEST_BROKER_TEST_ROOT'])
sys.path.insert(0, str(BROKER / 'tests'))
from agent_request_broker_test_support import kanban_env  # noqa: E402,F401
from test_native_block_approval import held, _button, OPERATION  # noqa: E402,F401
from conftest import synthetic_board_fence, historical_production_transport_contract  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[4]
loader = importlib.machinery.SourceFileLoader('native_refresh', str(ROOT / 'bin/firefox-controller-refresh'))
spec = importlib.util.spec_from_loader(loader.name, loader)
refresh = importlib.util.module_from_spec(spec)
loader.exec_module(refresh)


@pytest.fixture
def approved(held):
    b, conn, item, staged = held
    result = b.handle_telegram_callback(_button(b, conn, item, staged), actor='Joyful',
        chat_id='fixture-chat', user_id='fixture-owner')
    assert result['ok'], result
    event = conn.execute("SELECT * FROM task_events WHERE task_id=? AND kind='native_owner_decision_approved'",
                         (item.task_id,)).fetchone()
    receipt = json.loads(event['payload'])
    decision = dict(approval_event_id=event['id'], hold_event_id=receipt['event_id'],
                    blocker_generation=receipt['blocker_generation'], digest=receipt['digest'], scope=receipt['scope'])
    grant = dict(approval=receipt['approval_id'], scope=f'kanban:{b.board_name()}:{item.task_id}', journal_sha256='b' * 64)
    return b, conn, item, decision, grant


def invoke(monkeypatch, tmp_path, item, decision, grant, *, inspect_only=False):
    argv = ['controller-refresh', '--source-dir', str(tmp_path), '--expected-generation', 'epoch',
            '--expected-source', 'a' * 64, '--generation-recovery-request', item.request_id,
            '--generation-recovery-grant', json.dumps(grant), '--native-owner-decision', json.dumps(decision)]
    if inspect_only:
        argv.append('--check-authority-only')
    monkeypatch.setattr(sys, 'argv', argv)
    return refresh.main()


@pytest.mark.parametrize('held', [{'owner_operation_scope': OPERATION}], indirect=True)
def test_genuine_receipt_public_inspection_and_execution(approved, monkeypatch, tmp_path, capsys):
    b, conn, item, decision, grant = approved
    before = list(conn.iterdump())
    calls = []
    monkeypatch.setattr(refresh.subprocess, 'run', lambda argv, **kw: calls.append((argv, kw)))
    invoke(monkeypatch, tmp_path, item, decision, grant, inspect_only=True)
    assert json.loads(capsys.readouterr().out)['execution_authorized'] is False
    assert not calls
    for name in refresh.ASSETS:
        (tmp_path / name).write_text('# fixture managed asset\n')
    invoke(monkeypatch, tmp_path, item, decision, grant)
    assert len(calls) == 1
    assert calls[0][0][:8] == ['kubectl', '-n', 'ai', 'exec', '-i', 'deployment/firefox', '-c', 'kasm-firefox']
    assert json.loads(calls[0][1]['input'])['generation_grant'] == grant
    assert list(conn.iterdump()) == before


@pytest.mark.parametrize('held', [{'owner_operation_scope': OPERATION}], indirect=True)
@pytest.mark.parametrize('fault', ['approval_id', 'approval_event', 'hold', 'generation', 'digest', 'scope',
    'foreign_request', 'foreign_scope', 'missing_receipt', 'untrusted', 'altered_receipt', 'altered_hold',
    'missing_grant', 'wrong_grant', 'unconsumed', 'retired', 'missing_consumption', 'newer_hold',
    'newer_approval', 'newer_instruction', 'terminal', 'provenance', 'missing_provenance', 'foreign_run', 'live_run'])
def test_public_refusals_preserve_entire_database(approved, monkeypatch, tmp_path, fault):
    b, conn, item, decision, grant = approved
    if fault == 'approval_id':
        grant['approval'] = 'apr-foreign'
    elif fault == 'approval_event':
        decision['approval_event_id'] += 1
    elif fault == 'hold':
        decision['hold_event_id'] += 1
    elif fault == 'generation':
        decision['blocker_generation'] = 'blocker-foreign'
    elif fault == 'digest':
        decision['digest'] = 'c' * 64
    elif fault == 'scope':
        decision['scope']['owner_operation_scope']['target'] = 'different source and controller'
    elif fault == 'foreign_request':
        item = type('Foreign', (), {'request_id': 'ar-missing'})()
    elif fault == 'foreign_scope':
        grant['scope'] = 'kanban:agent-requests:t_foreign'
    elif fault in {'missing_receipt', 'untrusted', 'altered_receipt', 'altered_hold'}:
        with b.require_kanban().write_txn(conn):
            if fault == 'missing_receipt':
                conn.execute('DELETE FROM task_events WHERE id=?', (decision['approval_event_id'],))
            else:
                event_id = decision['hold_event_id'] if fault == 'altered_hold' else decision['approval_event_id']
                row = conn.execute('SELECT payload FROM task_events WHERE id=?', (event_id,)).fetchone()
                payload = json.loads(row['payload'])
                if fault == 'untrusted':
                    payload['source'] = 'worker-prose'
                elif fault == 'altered_receipt':
                    payload['scope']['owner_operation_scope']['target'] = 'altered source'
                else:
                    payload['owner_operation_scope']['safety_gates'] = 'No gates'
                conn.execute('UPDATE task_events SET payload=? WHERE id=?', (json.dumps(payload), event_id))
    elif fault in {'missing_grant', 'wrong_grant', 'unconsumed', 'retired', 'missing_consumption'}:
        with b.require_kanban().write_txn(conn):
            if fault == 'missing_grant':
                conn.execute('DELETE FROM kanban_owner_operation_grants')
            elif fault == 'wrong_grant':
                conn.execute("UPDATE kanban_owner_operation_grants SET approval_id='apr-other'")
            elif fault == 'missing_consumption':
                conn.execute("DELETE FROM task_events WHERE kind='blocker_generation_consumed'")
            else:
                conn.execute('UPDATE agent_request_human_blockers SET state=?',
                             ('current' if fault == 'unconsumed' else 'retired',))
    elif fault in {'provenance', 'missing_provenance', 'foreign_run', 'live_run'}:
        with b.require_kanban().write_txn(conn):
            if fault == 'provenance':
                conn.execute("UPDATE agent_request_steering_provenance SET provenance_json='{}'")
            elif fault == 'missing_provenance':
                conn.execute('DELETE FROM agent_request_steering_provenance')
            elif fault == 'foreign_run':
                conn.execute("UPDATE task_runs SET profile='star' WHERE task_id=?", (item.task_id,))
            else:
                conn.execute('UPDATE task_runs SET ended_at=NULL WHERE task_id=?', (item.task_id,))
    elif fault == 'newer_hold':
        assert b.require_kanban().block_task(conn, item.task_id, reason='Different owner decision',
            kind='needs_input', blocker_intent='owner_decision', owner_operation_scope={**OPERATION, 'target': 'other controller'},
            decision_scope={'decision': 'Different', 'target': 'different', 'constraints': 'different'},
            owner_decision={'question': 'Different?', 'user_impact': 'Different', 'recommended_option': 'Wait',
                            'approve_consequence': 'Different', 'decline_consequence': 'Wait'})
    elif fault in {'newer_approval', 'newer_instruction'}:
        # Deliberate competing event controls; never positive consent fixtures.
        with b.require_kanban().write_txn(conn):
            b.require_kanban()._append_event(conn, item.task_id,
                'native_owner_decision_approved' if fault == 'newer_approval' else 'agent_request_owner_instruction', {})
    elif fault == 'terminal':
        assert b.require_kanban().complete_task(conn, item.task_id, summary='Fixture finished')
    before = list(conn.iterdump())
    monkeypatch.setattr(refresh.subprocess, 'run', lambda *a, **kw: pytest.fail('No external mutation on refusal'))
    with pytest.raises((ValueError, KeyError)):
        invoke(monkeypatch, tmp_path, item, decision, grant)
    assert list(conn.iterdump()) == before


@pytest.mark.parametrize('held', [{'owner_operation_scope': OPERATION}], indirect=True)
def test_old_helper_rejection_and_historical_receipt_not_new_source_authority(approved, monkeypatch, tmp_path, capsys):
    b, conn, item, decision, grant = approved
    monkeypatch.setattr(refresh.subprocess, 'check_output', lambda *a, **kw: json.dumps({
        'status': 'ready', 'task_id': item.task_id, 'current_instruction': None}))
    with pytest.raises(ValueError, match='fresh exact scoped owner instruction'):
        refresh.owner_instruction_grant(item.request_id, grant)
    body = b.event_comment(request_id=item.request_id, actor='talon', action='steered',
                           summary='Source only', joy_steering='Do not perform runtime recovery.')
    b.require_kanban().add_comment(conn, item.task_id, 'talon', body)
    before = list(conn.iterdump())
    monkeypatch.setattr(refresh.subprocess, 'run', lambda *a, **kw: pytest.fail('Historical receipt is evidence only'))
    invoke(monkeypatch, tmp_path, item, decision, grant, inspect_only=True)
    assert json.loads(capsys.readouterr().out)['receipt_verified'] is True
    with pytest.raises(ValueError, match='newer execution instruction'):
        invoke(monkeypatch, tmp_path, item, decision, grant)
    assert list(conn.iterdump()) == before
