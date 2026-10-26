"""Explicit local grant, immutable provenance and no replacement of other scopes."""
import hashlib
import json

import pytest

from test_firefox_windows import A, B, close, engine, windows


def grant_for(controller):
    journals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(controller.path.parent.glob('*.json'))}
    return {'approval': 'apr-fixture-only', 'scope': A,
            'journal_sha256': hashlib.sha256(json.dumps(journals, sort_keys=True).encode()).hexdigest()}


def lost(engine, monkeypatch):
    controller, native = engine
    controller.acquire(A)
    controller.acquire(B)
    controller.state['actions']['old-key'] = {'state': 'delivered', 'scope': A, 'digest': 'old'}
    controller._save()
    resumed = windows.Windows(controller.path, connect=lambda: native)
    monkeypatch.setattr(windows, 'driver_request', lambda *args: {'ready': True})
    return resumed, native


def test_exact_grant_archives_every_journal_and_preserves_native_windows(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    original = controller.path.read_bytes()
    grant = grant_for(controller)
    calls = native.calls.copy()
    controller.reconcile_generation(grant)
    assert native.calls == calls
    archive = next((controller.path.parent / 'generation-history').glob('*.json'))
    bundle = json.loads(archive.read_text())
    assert bundle['journals'][controller.path.name].encode() == original
    assert archive.stat().st_mode & 0o777 == 0o400
    assert controller.state['actions']['old-key']['state'] == 'delivered'
    assert controller.recovery(B)['reason'] == 'binding_retired_with_history'
    with pytest.raises(windows.ControlError, match='no replacement authorized'):
        controller.acquire(B)
    assert len(native.tree) == 3
    # Synthetic native fixture has one owner selected by exact native identity.
    monkeypatch.setattr(controller, '_visible_context', lambda tree: tree[0])
    original_call = native._bidi
    def exchange(method, params, **kw):
        if method == 'browser.getClientWindows':
            return {'clientWindows': [{'clientWindow': 'root', 'active': True}]}
        return original_call(method, params, **kw)
    monkeypatch.setattr(native, '_bidi', exchange)
    new = controller.acquire(A).copy()
    assert new['context'] == 'context-3'
    assert controller.lifecycle(close())['closed'] is True
    assert len(native.tree) == 3  # Both old request windows still exist.
    saved = controller.path.read_bytes()
    controller.reconcile_generation(grant)
    assert controller.path.read_bytes() == saved
    assert len(list(archive.parent.glob('*.json'))) == 1


@pytest.mark.parametrize('state', ['started', 'pending', 'uncertain', 'unexpected'])
def test_pending_input_refuses_before_any_native_or_archive_change(engine, monkeypatch, state):
    controller, native = lost(engine, monkeypatch)
    controller.state['actions']['old-key']['state'] = state
    controller._save()
    before = controller.path.read_bytes()
    with pytest.raises(RuntimeError, match='pending or uncertain'):
        controller.reconcile_generation(grant_for(controller))
    assert controller.path.read_bytes() == before
    assert not (controller.path.parent / 'generation-history').exists()


def test_stale_safety_hash_and_occupied_driver_refuse(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    grant = grant_for(controller)
    controller.state['actions']['second'] = {'state': 'delivered'}
    controller._save()
    with pytest.raises(RuntimeError, match='journal changed'):
        controller.reconcile_generation(grant)
    monkeypatch.setattr(windows, 'driver_request', lambda *args: {'ready': False})
    with pytest.raises(RuntimeError, match='already occupied'):
        controller.reconcile_generation(grant_for(controller))
    assert not (controller.path.parent / 'generation-history').exists()


def test_committed_grant_survives_crash_before_connect(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    snapshot = controller.path.parent / 'old-snapshot.json'
    snapshot.write_text(json.dumps({'actions': {'historical-key': {'state': 'delivered'}}}))
    grant = grant_for(controller)
    controller.reconcile_generation(grant)
    resumed = windows.Windows(controller.path, connect=lambda: native)
    assert resumed.orphaned is False
    assert resumed.epoch == controller.epoch
    resumed.reconcile_generation(grant)
    assert resumed.state['windows'][B]['state'] == 'retired'
    assert 'historical-key' in resumed.legacy_keys
    assert 'old-key' in resumed.legacy_keys
    assert native.created == 2


def test_fsync_failure_keeps_old_generation_fenced(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    grant = grant_for(controller)
    before = controller.path.read_bytes()
    monkeypatch.setattr(controller, '_save', lambda: (_ for _ in ()).throw(OSError('fixture disk error')))
    with pytest.raises(OSError):
        controller.reconcile_generation(grant)
    assert controller.path.read_bytes() == before
    assert controller.orphaned is True
    assert controller.broken is True


@pytest.mark.parametrize('delivery_state', ['delivery_started', 'delivery_uncertain'])
def test_legacy_accessibility_input_is_also_a_hard_safety_gate(engine, monkeypatch, delivery_state):
    controller, native = lost(engine, monkeypatch)
    legacy = controller.path.parent / 'state.json'
    legacy.write_text(json.dumps({'action_keys': {'fixture-key': {'delivery_state': delivery_state}}}))
    before = controller.path.read_bytes()
    with pytest.raises(RuntimeError, match='pending or uncertain'):
        controller.reconcile_generation(grant_for(controller))
    assert controller.path.read_bytes() == before
    assert not (controller.path.parent / 'generation-history').exists()


def test_archive_conflict_and_failed_commit_are_not_overwritten(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    grant = grant_for(controller)
    history = controller.path.parent / 'generation-history'
    history.mkdir()
    archive = history / (grant['journal_sha256'] + '.json')
    archive.write_bytes(b'fixture conflicting immutable history')
    before = controller.path.read_bytes()
    with pytest.raises(RuntimeError, match='archive conflicts'):
        controller.reconcile_generation(grant)
    assert controller.path.read_bytes() == before
    assert archive.read_bytes() == b'fixture conflicting immutable history'


def test_retired_scope_cannot_receive_terminal_closure_receipt(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    controller.reconcile_generation(grant_for(controller))
    calls = native.calls.copy()
    with pytest.raises(RuntimeError):
        controller.lifecycle(close(B))
    assert native.calls == calls
    assert controller.state['windows'][B]['state'] == 'retired'


def historical_grant(controller):
    record = {'delivery_state': 'delivery_uncertain', 'operation': 'type',
              'workflow': 'fixture-only', 'created_at': 123}
    legacy = controller.path.parent / 'state.json'
    legacy.write_text(json.dumps({'action_keys': {'historical': record}}))
    grant = grant_for(controller)
    grant['retire_unresolved'] = [{'journal': 'state.json',
                                 'key_sha256': hashlib.sha256(b'historical').hexdigest(),
                                 'record_sha256': hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()}]
    return grant, legacy


def test_exact_historical_retirement_preserves_bytes_and_forbids_replay(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    grant, legacy = historical_grant(controller)
    original = legacy.read_bytes()
    calls = native.calls.copy()
    controller.reconcile_generation(grant)
    assert native.calls == calls
    assert legacy.read_bytes() == original
    archive = next((controller.path.parent / 'generation-history').glob('*.json'))
    assert json.loads(archive.read_text())['journals']['state.json'].encode() == original
    assert 'historical' in controller.legacy_keys
    assert 'historical' in windows.Windows(controller.path, connect=lambda: native).legacy_keys
    with pytest.raises(RuntimeError, match='no replay'):
        controller._input('type', {'action_key': 'historical'}, {}, {})
    controller.reconcile_generation(grant)
    changed = {**grant, 'retire_unresolved': []}
    with pytest.raises(RuntimeError, match='conflicting'):
        controller.reconcile_generation(changed)


@pytest.mark.parametrize('mutation', ['record', 'key', 'extra', 'missing', 'native', 'other-journal'])
def test_historical_exemption_is_exact_and_never_covers_other_input(engine, monkeypatch, mutation):
    controller, native = lost(engine, monkeypatch)
    grant, legacy = historical_grant(controller)
    state = json.loads(legacy.read_text())
    if mutation == 'record':
        state['action_keys']['historical']['workflow'] = 'changed'
    elif mutation == 'key':
        state['action_keys']['different'] = state['action_keys'].pop('historical')
    elif mutation == 'extra':
        state['action_keys']['new-input'] = {'delivery_state': 'delivery_started'}
    elif mutation == 'missing':
        state['action_keys'].clear()
    elif mutation == 'native':
        state['actions'] = state.pop('action_keys')
    else:
        (controller.path.parent / 'another.json').write_text(json.dumps(state))
    legacy.write_text(json.dumps(state))
    grant['journal_sha256'] = grant_for(controller)['journal_sha256']
    before = controller.path.read_bytes()
    calls = native.calls.copy()
    with pytest.raises(RuntimeError, match='pending or uncertain|missing or changed'):
        controller.reconcile_generation(grant)
    assert native.calls == calls
    assert controller.path.read_bytes() == before
    assert not (controller.path.parent / 'generation-history').exists()


def test_driver_startup_read_can_retry_without_native_mutation(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    attempts = []
    def status(method, path):
        attempts.append((method, path))
        if len(attempts) == 1:
            raise ConnectionRefusedError('fixture driver starting')
        return {'ready': True}
    monkeypatch.setattr(windows, 'driver_request', status)
    monkeypatch.setattr(windows.time, 'sleep', lambda delay: None)
    calls = native.calls.copy()
    controller.reconcile_generation(grant_for(controller))
    assert attempts == [('GET', '/status'), ('GET', '/status')]
    assert native.calls == calls


def second_loss(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    first = grant_for(controller)
    controller.reconcile_generation(first)
    controller.state['windows'][A] = {'state': 'open', 'epoch': controller.epoch}
    controller.state['controller'] = {'state': 'ready', 'epoch': controller.epoch,
                                     'pid': 123456, 'generation': 'previous-native-generation'}
    controller._save()
    monkeypatch.setattr(windows, 'process_generation', lambda pid: 'new-native-generation')
    return windows.Windows(controller.path, connect=lambda: native), native, first


@pytest.mark.parametrize('reference', ['apr-second-fixture-only', 'owner-instruction:123:' + 'a' * 64])
def test_second_generation_accepts_fresh_owner_instruction_without_native_input(engine, monkeypatch, reference):
    controller, native, first = second_loss(engine, monkeypatch)
    before = controller.path.read_bytes()
    calls = native.calls.copy()
    grant = grant_for(controller)
    grant['approval'] = reference
    controller.reconcile_generation(grant)
    assert controller.orphaned is False
    assert native.calls == calls
    archives = list((controller.path.parent / 'generation-history').glob('*.json'))
    assert len(archives) == 2
    bundle = json.loads((controller.path.parent / 'generation-history' /
                         (grant['journal_sha256'] + '.json')).read_text())
    assert bundle['journals']['windows.json'].encode() == before
    assert json.loads(bundle['journals']['windows.json'])['reconciliation']['approval'] == first['approval']
    assert 'old-key' in controller.state['retired_action_keys']
    assert controller.recovery(B)['reason'] == 'binding_retired_with_history'
    assert controller.state['windows'][B] == json.loads(before)['windows'][B]


def test_old_grant_cannot_unfence_a_second_lost_generation(engine, monkeypatch):
    controller, native, first = second_loss(engine, monkeypatch)
    before = controller.path.read_bytes()
    calls = native.calls.copy()
    controller.reconcile_generation(first)
    assert controller.orphaned is True
    assert controller.path.read_bytes() == before
    assert native.calls == calls


def test_new_grant_cannot_retire_an_active_generation(engine, monkeypatch):
    controller, native, first = second_loss(engine, monkeypatch)
    monkeypatch.setattr(controller, '_resumable', lambda: True)
    grant = grant_for(controller)
    grant['approval'] = 'owner-instruction:123:' + 'a' * 64
    with pytest.raises(RuntimeError, match='unconnected lost generation'):
        controller.reconcile_generation(grant)


@pytest.mark.parametrize('reference', ['owner-instruction:0:' + 'a' * 64,
                                      'owner-instruction:123:not-a-revision', 'unverified-prose'])
def test_malformed_owner_instruction_reference_refuses(engine, monkeypatch, reference):
    controller, native = lost(engine, monkeypatch)
    grant = grant_for(controller)
    grant['approval'] = reference
    before = controller.path.read_bytes()
    with pytest.raises(ValueError):
        controller.reconcile_generation(grant)
    assert controller.path.read_bytes() == before
