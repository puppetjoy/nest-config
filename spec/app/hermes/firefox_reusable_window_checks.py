"""Bounded public-schema journeys on a disposable, real Firefox only."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def run(engine, module, server, tool, call, base, emit, file_bytes, launcher):
    assert os.environ['FIREFOX_DISPOSABLE_CANARY'] == '1'
    scope = 'kanban:canary:t_publicfixture'
    unknown = json.loads(json.dumps(engine.state['actions']))
    root = dict(engine.state['windows']['owner'])
    first = dict(engine.state['windows'][scope])
    call('tab_lifecycle', {'action': 'release'})
    assert call('tab_lifecycle', {'action': 'recover'})['recovery']['next_action'] == 'acquire'
    # No explicit acquire: navigation is ordinary browsing after resumption.
    call('navigate', {'url': base + '/downloads'})
    assert engine.state['windows'][scope]['window'] != first['window']
    downloaded = call('download', {'selector': '#download'})
    assert Path(downloaded['file_path']).read_bytes() == file_bytes
    assert downloaded['sha256'] == hashlib.sha256(file_bytes).hexdigest()
    assert 'data' not in downloaded
    call('screenshot', {})
    assert engine.state['actions'] == unknown
    assert engine.state['windows']['owner'] == root
    emit('release-resume-download', exact_bytes=len(file_bytes), sha256=downloaded['sha256'], no_acquisition_ceremony=True)

    # A worker-run boundary does not change request/window identity.
    binding = dict(engine.state['windows'][scope])
    engine.browser.close()
    resumed = module.Windows(engine.path)
    server.windows = resumed
    call('page_snapshot', {})
    assert resumed.state['windows'][scope]['window'] == binding['window']
    assert resumed.state['actions'] == unknown
    engine = resumed
    emit('controller-restart-and-request-continuation', same_window=True, unknown_actions_unchanged=True)

    # Actual schema handlers, in distinct synthetic worker contexts, concurrently.
    local = threading.local()
    original_env = tool._session_env
    def session_env(key):
        return {'HERMES_KANBAN_TASK': getattr(local, 'task', 't_publicfixture'), 'HERMES_KANBAN_BOARD': 'canary'}.get(key, '')
    tool._session_env = session_env
    def worker(task):
        local.task = task
        call('navigate', {'url': base + '/downloads'})
        result = call('download', {'selector': '#download'})
        assert result['sha256'] == hashlib.sha256(file_bytes).hexdigest()
        return dict(engine.state['windows']['kanban:canary:' + task])
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(worker, ['t_parallel_a', 't_parallel_b']))
        assert a['window'] != b['window'] != binding['window']
        for task in ['t_parallel_a', 't_parallel_b']:
            local.task = task
            call('tab_lifecycle', {'action': 'release'})
    finally:
        tool._session_env = original_env
    emit('concurrent-public-workers', distinct_windows=True, shared_authenticated_profile=True)

    call('tab_lifecycle', {'action': 'keep_open', 'lease_seconds': 60})
    before = dict(engine.state['windows'][scope])
    time.sleep(61)  # One real idle-expiry interval, not a soak or simulated clock.
    deadline = time.monotonic() + 7
    while engine.state['windows'][scope]['state'] != 'closed':
        assert time.monotonic() < deadline
        time.sleep(.2)  # The actual endpoint janitor, not a direct test sweep.
    call('navigate', {'url': base + '/downloads'})
    assert engine.state['windows'][scope]['window'] != before['window']
    assert call('download', {'selector': '#download'})['sha256'] == downloaded['sha256']
    assert engine.state['actions'] == unknown
    emit('real-idle-expiry-reuse', expiry_seconds=60, browsing_restored=True)

    # Kill only this disposable Firefox. The product code never restarts it;
    # ordinary launcher restart models container supervision with the same profile.
    old = dict(engine.state['controller'])
    os.kill(old['pid'], signal.SIGKILL)
    launcher.wait(timeout=25)
    launcher = subprocess.Popen(['sh', '/opt/nest/firefox/bin/nest-firefox-browser.sh'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 45
    while True:
        try:
            with socket.create_connection(('127.0.0.1', 9222), timeout=.2):
                break
        except OSError:
            assert time.monotonic() < deadline
            time.sleep(.2)
    time.sleep(3)
    call('navigate', {'url': base + '/downloads'})
    assert engine.state['controller']['generation'] != old['generation']
    assert engine.state['actions'] == unknown
    assert call('download', {'selector': '#download'})['sha256'] == downloaded['sha256']
    assert list((engine.path.parent / 'generation-history').glob('*.json'))
    emit('real-disposable-browser-crash', original_journal_archived=True, unknown_actions_unchanged=True, ordinary_browsing_restored=True)

    # Deliberate terminal close remains distinct from temporary disposal.
    binding = dict(engine.state['windows'][scope])
    receipt = engine.lifecycle({'action': 'close', 'scope': scope, 'terminal_event_id': 42, 'terminal_status': 'completed'})
    assert receipt.get('closed') or receipt.get('already_closed')
    assert engine.recovery(scope)['next_action'] == 'none'
    refused = call('navigate', {'url': base + '/downloads'}, ('error',))
    assert engine.state['windows'][scope]['state'] == 'closed'
    assert not any(c['context'] == binding['context'] for c in engine._tree())
    emit('deliberate-terminal-cleanup', fenced=True, exact_native_absence=True)
    return engine, launcher
