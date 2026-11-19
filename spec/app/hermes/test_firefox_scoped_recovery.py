"""Historical retirement is per binding, not a global browser admission list."""
import time

import pytest

from test_firefox_windows import A, B, close, engine, windows
from test_firefox_generation_reconciliation import grant_for, lost

# The affected ordinary caller, not the generation-reconciliation acceptance ticket.
CATALOG = 'kanban:agent-requests:t_b184dfb4'


def reconciled(engine, monkeypatch):
    controller, native = lost(engine, monkeypatch)
    controller.reconcile_generation(grant_for(controller))
    monkeypatch.setattr(controller, '_visible_context', lambda tree: tree[0])
    original = native._bidi
    def exchange(method, params, **kw):
        if method == 'browser.getClientWindows':
            return {'clientWindows': [{'clientWindow': 'root', 'active': True}]}
        return original(method, params, **kw)
    monkeypatch.setattr(native, '_bidi', exchange)
    return controller, native


def binding_grant(controller, scope=B):
    return {'approval': 'apr-fixture-only-later', 'scope': scope,
            'archive': controller.state['windows'][scope]['archive'],
            'epoch': controller.epoch, 'expires_at': int(time.time()) + 300}


def test_never_seen_ordinary_catalog_scope_can_acquire_after_reconciliation(engine, monkeypatch):
    controller, native = reconciled(engine, monkeypatch)
    assert CATALOG not in controller.state['windows']
    assert controller.acquire(CATALOG)['state'] == 'open'
    assert controller.acquire(CATALOG)['state'] == 'open'
    assert native.created == 3
    assert controller.acquire(B)['state'] == 'open'


def test_local_approved_retired_binding_gets_one_new_identity_and_keeps_history(engine, monkeypatch):
    controller, native = reconciled(engine, monkeypatch)
    archive = controller.path.parent / 'generation-history' / controller.state['windows'][B]['archive']
    original = archive.read_bytes()
    old_tree = native.tree.copy()
    grant = binding_grant(controller)
    controller.authorize_binding(grant)
    assert controller.recovery(B)['next_action'] == 'acquire'
    assert native.created == 2  # Authorization is not creation or replay.
    controller.authorize_binding(grant)
    fresh = controller.acquire(B).copy()
    controller.authorize_binding(grant)
    assert controller.acquire(B) == fresh
    assert native.created == 3
    assert native.tree[:3] == old_tree
    assert archive.read_bytes() == original
    assert controller.state['binding_recoveries'][B]['archive'] == archive.name
    with pytest.raises(RuntimeError, match='no replay'):
        controller._input('type', {'action_key': 'old-key'}, {}, {})
    assert controller.lifecycle(close(B))['closed'] is True
    with pytest.raises(RuntimeError):
        controller.authorize_binding(grant)
    assert native.created == 3


@pytest.mark.parametrize('mutation', ['wrong_scope', 'archive', 'epoch', 'expired', 'owner', 'unscoped', 'extra'])
def test_invalid_local_grant_never_changes_state_or_native_windows(engine, monkeypatch, mutation):
    controller, native = reconciled(engine, monkeypatch)
    grant = binding_grant(controller)
    if mutation == 'wrong_scope':
        grant['scope'] = CATALOG
    elif mutation == 'expired':
        grant['expires_at'] = int(time.time()) - 1
    elif mutation == 'owner':
        grant['scope'] = 'owner'
    elif mutation == 'unscoped':
        grant.pop('scope')
    elif mutation == 'extra':
        grant['trusted'] = True
    else:
        grant[mutation] = 'wrong'
    before = controller.path.read_bytes()
    calls = native.calls.copy()
    with pytest.raises((ValueError, RuntimeError)):
        controller.authorize_binding(grant)
    assert controller.path.read_bytes() == before
    assert native.calls == calls


def test_lost_generation_and_pending_input_prevent_local_authorization(engine, monkeypatch):
    controller, native = reconciled(engine, monkeypatch)
    grant = binding_grant(controller)
    controller.orphaned = True
    with pytest.raises(RuntimeError):
        controller.authorize_binding(grant)
    controller.orphaned = False
    controller.state['actions']['pending'] = {'state': 'started'}
    controller._save()
    with pytest.raises(RuntimeError):
        controller.authorize_binding(grant)
    assert native.created == 2


def test_terminal_retired_binding_cannot_use_an_otherwise_valid_grant(engine, monkeypatch):
    controller, native = reconciled(engine, monkeypatch)
    grant = binding_grant(controller)
    with pytest.raises(RuntimeError, match='terminal scope fenced'):
        controller.lifecycle(close(B))
    with pytest.raises(RuntimeError, match='terminal scope'):
        controller.authorize_binding(grant)
    assert controller.recovery(B)['next_action'] == 'none'
    assert native.created == 2


def test_failed_grant_commit_and_lost_new_create_never_replay(engine, monkeypatch):
    controller, native = reconciled(engine, monkeypatch)
    grant = binding_grant(controller)
    save = controller._save
    monkeypatch.setattr(controller, '_save', lambda: (_ for _ in ()).throw(OSError('fixture disk error')))
    with pytest.raises(OSError):
        controller.authorize_binding(grant)
    assert controller.state['windows'][B]['state'] == 'retired'
    monkeypatch.setattr(controller, '_save', save)
    controller.authorize_binding(grant)
    native.fail_create = True
    with pytest.raises(RuntimeError):
        controller.acquire(B)
    controller.authorize_binding(grant)
    with pytest.raises(RuntimeError):
        controller.acquire(B)
    assert native.created == 3


def test_expiry_after_authorization_never_allocates(engine, monkeypatch):
    controller, native = reconciled(engine, monkeypatch)
    grant = binding_grant(controller)
    controller.authorize_binding(grant)
    monkeypatch.setattr(windows.time, 'time', lambda: grant['expires_at'] + 1)
    assert controller.recovery(B)['new_binding_allowed'] is True
    assert controller.acquire(B)['state'] == 'open'
    assert native.created == 3
