"""Two-phase disposable container-restart canary; never use an owner profile.

Run setup, restart the SAME isolated container, then run verify. No network or
user mounts are needed. The local grant is synthetic fixture authority only.
"""
import hashlib
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, '/opt/nest/firefox/bin')
import firefox_windows as windows

ROOT = Path('/home/kasm-user/.local/state/nest-firefox-ui/closed-scope-canary')
SCOPE = 'kanban:restart-fixture:t_closed'
OTHER = 'kanban:restart-fixture:t_old_active'
PATH = ROOT / 'windows.json'
PHASE = sys.argv[1]

if PHASE == 'setup':
    assert not PATH.exists(), 'Never reuse previous fixture state'
    deadline = time.monotonic() + 40
    while True:
        try:
            assert windows.driver_request('GET', '/status')['ready'] is True
            with socket.create_connection(('127.0.0.1', 2828), timeout=1):
                pass
            break
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    # Fresh fixture only: finish onboarding before declaring owner baseline.
    time.sleep(12)
    engine = windows.Windows(PATH)
    for extra in engine._tree()[1:]:
        engine._call('browsingContext.close', {'context': extra['context'], 'promptUnload': False})
    engine.acquire('owner')
    engine.dispatch('tabs', {'scope': SCOPE, 'action': 'acquire', 'lease_seconds': 60})
    engine.acquire(OTHER)
    engine.dispatch('tabs', {'scope': SCOPE, 'action': 'release'})
    assert engine.state['windows'][SCOPE]['state'] == 'closed'
    (ROOT / 'tombstone.fixture').write_text(json.dumps(engine.state['windows'][SCOPE], sort_keys=True))
    (ROOT / 'generation.fixture').write_text(engine.state['controller']['generation'])
    print(json.dumps({'phase': 'setup', 'closed': True, 'native_contexts': len(engine._tree())}), flush=True)
elif PHASE == 'verify':
    deadline = time.monotonic() + 40
    while True:
        try:
            assert windows.driver_request('GET', '/status')['ready'] is True
            with socket.create_connection(('127.0.0.1', 2828), timeout=1):
                pass
            break
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    engine = windows.Windows(PATH)
    assert engine.orphaned and not engine._resumable(), 'A real native generation change is required'
    old_generation = (ROOT / 'generation.fixture').read_text()
    tombstone = json.loads((ROOT / 'tombstone.fixture').read_text())
    raw = PATH.read_bytes()
    journals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob('*.json'))}
    grant = {'scope': SCOPE, 'approval': 'apr-disposable-restart-fixture',
             'journal_sha256': hashlib.sha256(json.dumps(journals, sort_keys=True).encode()).hexdigest()}
    original_request = windows.driver_request
    calls = []
    def status_only(method, path, *args, **kwargs):
        assert (method, path) == ('GET', '/status'), 'No native mutation during reconciliation'
        calls.append((method, path))
        return original_request(method, path, *args, **kwargs)
    windows.driver_request = status_only
    engine.reconcile_generation(grant)
    windows.driver_request = original_request
    assert calls and engine.state['windows'][SCOPE] == tombstone
    archive = ROOT / 'generation-history' / (grant['journal_sha256'] + '.json')
    assert json.loads(archive.read_text())['journals']['windows.json'].encode() == raw
    assert engine.state['windows'][OTHER]['state'] == 'retired'
    try:
        engine.acquire(SCOPE)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Closed scope reopened')
    # New native session: preserve all existing/unknown restored contexts.
    tree = engine._tree()
    assert engine.state['controller']['generation'] != old_generation
    baseline = {(c['context'], c['clientWindow']) for c in tree}
    fresh = 'kanban:restart-fixture:t_new'
    binding = engine.acquire(fresh).copy()
    assert len(engine._tree()) == len(baseline) + 1
    engine.dispatch('tabs', {'scope': fresh, 'action': 'release'})
    assert {(c['context'], c['clientWindow']) for c in engine._tree()} == baseline
    assert not any(c['context'] == binding['context'] for c in engine._tree())
    before = PATH.read_bytes()
    engine.reconcile_generation(grant)
    assert PATH.read_bytes() == before
    assert engine.state['windows'][SCOPE] == tombstone
    print(json.dumps({'phase': 'verify', 'real_native_generation_changed': True,
                      'closed_scope_preserved': True, 'native_mutations_during_reconcile': False,
                      'archive_exact': True, 'old_active_scope_retired_not_closed': True,
                      'fresh_scope_release_exact': True, 'unrelated_contexts_preserved': True,
                      'baseline_contexts': len(baseline), 'reconciliation_idempotent': True}), flush=True)
else:
    raise ValueError('Expected setup or verify')
