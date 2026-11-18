"""Source qualification: modeled storage/manager; real unprivileged processes.

No test mounts, changes cgroups, installs units, calls providers or enrolls a
production board. Test-owned files live beneath TMPDIR and are bounded.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('wizard_capsule', ROOT / 'files/app/hermes/wizard_capsule.py')
assert SPEC is not None and SPEC.loader is not None
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)
SUPERVISOR_SPEC = importlib.util.spec_from_file_location('wizard_supervisor', ROOT / 'files/app/hermes/wizard_capsule_supervisor.py')
assert SUPERVISOR_SPEC is not None and SUPERVISOR_SPEC.loader is not None
S = importlib.util.module_from_spec(SUPERVISOR_SPEC)
with patch.dict(sys.modules, {'wizard_capsule': C}):
    SUPERVISOR_SPEC.loader.exec_module(S)


class ModeledStorage:
    qualification = 'modeled-not-installed'

    def __init__(self):
        self.calls = 0
        self.fail = False
        self.replaced = False

    def create_storage(self, selection):
        self.calls += 1
        Path(selection['root']).mkdir()
        if self.fail:
            raise TimeoutError('modeled acknowledgement lost after creation')

    def storage(self, selection):
        return dict(identity=dict(root=C.identity(selection['root']), mount_id='modeled-2' if self.replaced else 'modeled-1'),
                    byte_limit=16384, inode_limit=32, bytes_available=16384, inodes_available=32,
                    writable=list(C.WRITABLE), durable=False)


class CapsuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'board.sqlite'
        db = sqlite3.connect(self.board)
        db.executescript('CREATE TABLE history(payload TEXT); INSERT INTO history VALUES (\'original failure and unknown charges\');')
        db.close()
        self.original = self.board.read_bytes()
        (self.root / 'ledger').mkdir(mode=0o700)
        (self.root / 'roots').mkdir()
        self.image = self.root / 'image.squashfs'
        self.image.write_bytes(b'explicitly modeled image; not a bootable runtime')
        self.policy = dict(schema=1, board_path=str(self.board), task_id='original', request_id='request-original',
                           source_policy_sha256='a' * 64, image_path=str(self.image),
                           image_sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
                           root_parent=str(self.root / 'roots'), uid=65536, gid=65536,
                           bytes=16384, inodes=32, cpu_max=[10000, 100000], memory_max=1048576,
                           memory_swap_max=0, pids_max=16, cpu_budget_usec=2000000,
                           max_seconds=5, poll_usec=10000, kill_reserve_usec=10000)
        self.policy_path = self.root / 'policy.json'
        self.pin = self.write_policy()
        # Only privilege/ownership are modeled. No production bypass flag exists.
        for name, replacement in [('service_guard', lambda: None), ('root_parent', lambda p: Path(p)),
                                  ('protected', lambda p, directory=False: Path(p))]:
            mock = patch.object(C, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        self.store = C.Store(self.root / 'ledger')
        self.addCleanup(self.store.close)
        self.backend = ModeledStorage()
        self.capsules = C.Capsules(self.store, self.backend)

    def tearDown(self):
        self.assertEqual(self.board.read_bytes(), self.original, 'all original history must remain unchanged')

    def write_policy(self):
        self.policy_path.write_text(C.encoded(self.policy))
        return hashlib.sha256(self.policy_path.read_bytes()).hexdigest()

    def select(self):
        p = C.read_policy(str(self.policy_path), self.pin)
        return self.capsules._select(p, self.policy_path, self.pin)

    def ready(self):
        s = self.select()
        result = self.capsules.provision(s['capsule'])
        self.assertFalse(result['complete'])
        return s

    def baseline(self):
        return dict(identity=dict(path='/modeled/root', device=1, inode=2), context=C.context(),
                    cpu_usec=100, oom_kill=0, populated=1,
                    limits={'cpu.max': '10000 100000', 'memory.max': '1048576', 'memory.swap.max': '0', 'pids.max': '16'})

    def test_duplicate_keeps_exact_root_deadline_and_baselines(self):
        first = self.ready()
        before = self.store.events(first['capsule'])
        self.assertEqual(first, self.select())
        self.capsules.provision(first['capsule'])
        self.assertEqual(self.backend.calls, 1)
        self.assertEqual(before, self.store.events(first['capsule']))
        observation = self.capsules.observe(first['capsule'])
        self.assertEqual(observation['qualification'], 'modeled-not-installed')
        self.assertFalse(observation['complete'])
        with self.assertRaisesRegex(C.Refused, 'complete admission unavailable'):
            self.capsules.admit(first['capsule'])

    def test_concurrent_duplicates_one_selection_and_attempt(self):
        def call(_):
            store = C.Store(self.root / 'ledger')
            try:
                c = C.Capsules(store, self.backend)
                selected = c._select(self.policy, self.policy_path, self.pin)
                c.provision(selected['capsule'])
                return selected
            finally:
                store.close()
        # SQLite connections are owned by each caller; flock serializes storage effects.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(call, range(16)))
        self.assertTrue(all(v == results[0] for v in results))
        self.assertEqual(self.backend.calls, 1)

    def test_crash_unknown_never_replays_or_adopts_root(self):
        s = self.select()
        self.backend.fail = True
        with self.assertRaises(TimeoutError):
            self.capsules.provision(s['capsule'])
        history = self.store.events(s['capsule'])
        with self.assertRaisesRegex(C.Refused, 'uncertain creation'):
            self.capsules.provision(s['capsule'])
        self.assertEqual(self.backend.calls, 1)
        self.assertEqual(history, self.store.events(s['capsule']))
        self.assertTrue(Path(s['root']).exists(), 'no destructive cleanup')
        self.assertEqual(history[-1]['kind'], 'creation_unknown')
        reconciled = self.capsules.reconcile(s['capsule'])
        self.assertEqual(reconciled['root'], s['root'])
        self.assertEqual(reconciled['ownership'], 'unknown')
        self.assertFalse(reconciled['replay'])
        self.assertEqual(history, self.store.events(s['capsule']))

    def test_crash_before_create_retains_attempt_and_no_second_root(self):
        s = self.select()
        self.store.append(s['capsule'], 'create_attempt', dict(root=s['root'], cpu_baseline='unknown'))
        with self.assertRaises(FileNotFoundError):
            self.capsules.provision(s['capsule'])
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(self.select(), s)

    def test_conflicting_policy_and_reboot_refuse_without_reset(self):
        s = self.ready()
        before = '\n'.join(self.store.conn.iterdump())
        other = dict(self.policy, bytes=32768)
        with self.assertRaisesRegex(C.Refused, 'conflicting'):
            self.capsules._select(other, self.policy_path, self.pin)
        with patch.object(C, 'context', return_value=dict(host='same-host', boot='later-boot')):
            with self.assertRaises(C.Refused):
                self.select()
            with self.assertRaises(C.Refused):
                self.capsules.observe(s['capsule'])
        self.assertEqual(before, '\n'.join(self.store.conn.iterdump()))

    def test_revocation_preserves_evidence_and_refuses(self):
        s = self.ready()
        self.capsules.revoke(s['capsule'])
        before = self.store.events(s['capsule'])
        self.capsules.revoke(s['capsule'])
        self.assertEqual(before, self.store.events(s['capsule']))
        with self.assertRaisesRegex(C.Refused, 'revoked'):
            self.capsules.provision(s['capsule'])
        self.assertEqual(self.backend.calls, 1)

    def test_changed_image_and_policy_refuse(self):
        s = self.ready()
        self.image.write_bytes(b'revoked runtime')
        with self.assertRaisesRegex(C.Refused, 'image changed'):
            self.capsules.observe(s['capsule'])
        self.policy_path.write_text('{}')
        with self.assertRaisesRegex(C.Refused, 'policy changed'):
            self.capsules.observe(s['capsule'])

    def test_replaced_mount_and_root_refuse(self):
        s = self.ready()
        self.backend.replaced = True
        with self.assertRaisesRegex(C.Refused, 'replaced'):
            self.capsules.observe(s['capsule'])
        self.backend.replaced = False
        Path(s['root']).rename(s['root'] + '-retained')
        Path(s['root']).mkdir()
        with self.assertRaisesRegex(C.Refused, 'replaced'):
            self.capsules.provision(s['capsule'])
        self.assertEqual(self.backend.calls, 1)

    def test_board_replacement_refuses_second_selection(self):
        self.select()
        self.board.rename(self.root / 'old-board')
        self.board.write_bytes(self.original)
        with self.assertRaisesRegex(C.Refused, 'board identity replaced'):
            self.select()

    def test_caller_receipt_and_unselected_routes_not_authority(self):
        with self.assertRaisesRegex(C.Refused, 'unknown capsule'):
            self.capsules.admit('caller-claims-complete')
        self.policy['provider'] = 'arbitrary-sdk'
        self.pin = self.write_policy()
        with self.assertRaisesRegex(C.Refused, 'exact versioned'):
            self.select()
        self.assertEqual(self.backend.calls, 0)

    def test_strict_policy_types_and_cpu_reserve(self):
        for key, value in [('schema', True), ('inodes', True), ('memory_swap_max', False), ('cpu_max', [True, 10000])]:
            with self.subTest(key=key):
                original = self.policy[key]
                self.policy[key] = value
                self.pin = self.write_policy()
                with self.assertRaises(C.Refused):
                    self.select()
                self.policy[key] = original
        with self.assertRaisesRegex(C.Refused, 'reserve consumes'):
            C.cutoff(dict(self.policy, cpu_budget_usec=1))

    def test_immutable_ledger_and_no_replace(self):
        s = self.ready()
        for sql in ('DELETE FROM selections', "UPDATE selections SET payload='{}'",
                    'DELETE FROM events', "UPDATE events SET payload='{}'",
                    "INSERT OR REPLACE INTO selections SELECT * FROM selections",
                    'INSERT OR REPLACE INTO events SELECT * FROM events'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.store.conn.execute(sql)
        self.assertEqual(self.select(), s)

    def test_unit_policy_has_no_host_home_network_or_delegation(self):
        props = C.launch_properties(self.select())
        for key, value in [('PrivateNetwork', 'yes'), ('RestrictAddressFamilies', 'AF_UNIX'),
                           ('Delegate', 'no'), ('ProtectSystem', 'strict'), ('MemorySwapMax', '0'),
                           ('KillMode', 'control-group'), ('CPUQuota', '10%')]:
            self.assertEqual(props[key], value)
        self.assertEqual(props['ReadWritePaths'], '/request')
        self.assertNotIn('PYTHONPATH', props['Environment'])
        self.assertIn('/request/logs/', props['StandardOutput'])

    def test_deadline_cpu_oom_and_detached_descendants(self):
        s, baseline = self.select(), self.baseline()
        for reason, update, now in [('deadline', {}, s['deadline_ns']),
                                    ('lifetime_cpu', dict(cpu_usec=baseline['cpu_usec'] + s['cutoff']['stop_at_usec']), 0),
                                    ('oom', dict(oom_kill=1), 0)]:
            with self.subTest(reason=reason):
                result = C.supervise_tick(s, baseline, dict(baseline, **update), supervisor_alive=True, now_ns=now)
                self.assertTrue(result['stop'])
                self.assertEqual(result['reason'], reason)
                self.assertTrue(result['descendants_present'])
                self.assertFalse(result['reap_proven'])
                self.assertFalse(result['complete'])

    def test_unknown_cpu_reboot_replacement_and_watchdog_loss(self):
        s, baseline = self.select(), self.baseline()
        for observed, alive in [(None, True), (dict(baseline, cpu_usec=0), True),
                                (dict(baseline, identity={}), True),
                                (dict(baseline, context={}), True), (baseline, False)]:
            result = C.supervise_tick(s, baseline, observed, supervisor_alive=alive, now_ns=0)
            self.assertTrue(result['stop'])
            self.assertTrue(result['cpu_unknown'])
            self.assertFalse(result['complete'])
        wrong = deepcopy(baseline)
        wrong['limits']['memory.max'] = 'max'
        result = C.supervise_tick(s, wrong, wrong, supervisor_alive=True, now_ns=0)
        self.assertEqual(result['reason'], 'unselected_limits')

    def test_bounded_modeled_quota_overrun_not_kernel_enforcement(self):
        # Real bounded file writes; a model rejects the attempted extra byte/inode.
        limit, objects, written = 16384, 4, 0
        refused = False
        for index in range(objects + 1):
            block = b'x' * 4096
            if index >= objects or written + len(block) > limit:
                refused = True
                break
            (self.root / f'quota-fixture-{index}').write_bytes(block)
            written += len(block)
        self.assertTrue(refused)
        self.assertEqual(written, limit)
        self.assertEqual(len(list(self.root.glob('quota-fixture-*'))), objects)

    def test_real_linux_readback_refuses_ordinary_directory_as_quota(self):
        s = self.ready()
        with self.assertRaisesRegex(C.Refused, 'exact real quota mount'):
            C.LinuxStorage.storage(s)

    def test_linux_create_source_uses_exact_finite_tmpfs_not_zfs_or_shared_home(self):
        s = self.select()
        with patch.object(C.subprocess, 'run') as run, patch.object(C.os, 'chown') as chown:
            C.LinuxStorage.create_storage(s)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ['/bin/mount', '-t', 'tmpfs', '-o'])
        self.assertIn('size=16384,nr_inodes=32', argv[4])
        self.assertEqual(argv[-1], s['root'])
        self.assertEqual(chown.call_count, len(C.WRITABLE))
        self.assertNotIn('zfs', ' '.join(argv))


    def modeled_manager(self, selected):
        root = self.baseline()
        root.update(cpu_usec=0, populated=0)
        root['identity']['path'] = '/sys/fs/cgroup/modeled-request'
        return dict(context=C.context(),
                    root=dict(Id='request.slice', InvocationID='modeled-root-invocation', ControlGroup='/modeled-request', cgroup=root),
                    supervisor=dict(Id='watch.service', InvocationID='modeled-watch-invocation', ControlGroup='/modeled-watch',
                                    process=C.process(os.getpid())))

    def test_manager_binding_is_prospective_and_never_resets_baseline(self):
        selected = self.ready()
        manager = self.modeled_manager(selected)
        with patch.object(S, 'manager_readback', return_value=manager):
            first = S.bind_manager(self.capsules, selected['capsule'])
            self.assertEqual(first, S.bind_manager(self.capsules, selected['capsule']))
            manager['root']['InvocationID'] = 'replaced'
            with self.assertRaisesRegex(C.Refused, 'manager replaced'):
                S.bind_manager(self.capsules, selected['capsule'])
        self.assertEqual(len([e for e in self.store.events(selected['capsule']) if e['kind'] == 'manager_bound']), 1)

    def test_manager_historical_cpu_and_population_refuse(self):
        selected = self.ready()
        for key in ('cpu_usec', 'populated', 'oom_kill'):
            manager = self.modeled_manager(selected)
            manager['root']['cgroup'][key] = 1
            with patch.object(S, 'manager_readback', return_value=manager):
                with self.assertRaisesRegex(C.Refused, 'fresh unused'):
                    S.bind_manager(self.capsules, selected['capsule'])

    def test_watchdog_loop_deadline_cpu_unknown_and_unresolved_kill(self):
        selected = self.ready()
        manager = self.modeled_manager(selected)
        with patch.object(S, 'manager_readback', return_value=manager):
            S.bind_manager(self.capsules, selected['capsule'])
        manager['root']['cgroup']['cpu_usec'] = selected['cutoff']['stop_at_usec']
        with patch.object(S, 'manager_readback', return_value=manager), patch.object(S, 'kill_exact_root', return_value=dict(kill_requested=True, reap_proven=False)) as kill:
            result = S.run_watchdog(self.capsules, selected['capsule'])
        self.assertEqual(result['outcome']['reason'], 'lifetime_cpu')
        self.assertFalse(result['kill']['reap_proven'])
        kill.assert_called_once_with(manager['root']['cgroup']['identity'])
        with patch.object(S, 'manager_readback', side_effect=OSError('kernel read unknown')), patch.object(S, 'kill_exact_root', side_effect=OSError('kill unresolved')):
            result = S.run_watchdog(self.capsules, selected['capsule'])
        self.assertTrue(result['outcome']['cpu_unknown'])
        self.assertTrue(result['kill']['kill_unknown'])
        self.assertFalse(result['complete'])

    def test_watchdog_loss_before_binding_never_invents_baseline(self):
        selected = self.ready()
        with self.assertRaisesRegex(C.Refused, 'baseline required'):
            S.run_watchdog(self.capsules, selected['capsule'])

    def test_replaced_or_foreign_kernel_root_never_killed(self):
        for path in ('/sys/fs/cgroup', str(self.root)):
            with self.assertRaises(C.Refused):
                S.kill_exact_root(C.identity(path))

    def native_modules(self, request='request-original', requests=0):
        # Explicit modeled Native protocol, not a genuine Native producer.
        base = ModuleType('hermes_cli')
        guard = ModuleType('hermes_cli.kanban_wizard_claims')
        guard.service_guard = lambda conn: None
        usage = ModuleType('hermes_cli.kanban_request_usage')
        usage.current = lambda conn, task_id: dict(request_id=request)
        usage.snapshot = lambda conn, task_id: dict(requests=requests, unresolved=0)
        base.kanban_request_usage = usage
        kb = ModuleType('hermes_cli.kanban_db')
        @contextmanager
        def write_txn(conn):
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK')
                raise
        kb.write_txn = write_txn
        base.kanban_db = kb
        return patch.dict(sys.modules, {'hermes_cli': base, 'hermes_cli.kanban_wizard_claims': guard,
                                       'hermes_cli.kanban_request_usage': usage, 'hermes_cli.kanban_db': kb})

    def native_fixture(self):
        path = self.root / 'modeled-native.sqlite'
        conn = sqlite3.connect(path, isolation_level=None)
        conn.execute('CREATE TABLE task_runs(task_id TEXT)')
        self.addCleanup(conn.close)
        self.policy['board_path'] = str(path)
        self.pin = self.write_policy()
        return conn

    def test_public_selection_prospective_protocol_and_original_history(self):
        conn = self.native_fixture()
        args = dict(native_conn=conn, policy_path=self.policy_path, policy_sha256=self.pin)
        with self.native_modules():
            conn.execute('BEGIN')
            with self.assertRaisesRegex(C.Refused, 'own the Native writer'):
                self.capsules.select(**args)
            conn.execute('ROLLBACK')
            selected = self.capsules.select(**args)
            self.assertEqual(selected, self.capsules.select(**args))
            conn.execute("INSERT INTO task_runs VALUES ('original')")
            before = '\n'.join(self.store.conn.iterdump())
            with self.assertRaisesRegex(C.Refused, 'historical population'):
                self.capsules.select(**args)
            self.assertEqual(before, '\n'.join(self.store.conn.iterdump()))

    def test_public_selection_wrong_board_and_envelope_refuse(self):
        conn = self.native_fixture()
        args = dict(native_conn=conn, policy_path=self.policy_path, policy_sha256=self.pin)
        with self.native_modules(request='foreign-request'):
            with self.assertRaisesRegex(C.Refused, 'exact prospective'):
                self.capsules.select(**args)
        with self.native_modules(requests=1):
            with self.assertRaisesRegex(C.Refused, 'historical population'):
                self.capsules.select(**args)
        self.policy['board_path'] = str(self.board)
        self.pin = self.write_policy()
        args['policy_sha256'] = self.pin
        with self.native_modules():
            with self.assertRaisesRegex(C.Refused, 'another board'):
                self.capsules.select(**args)

    def test_versioned_inspector_real_board_identity_modeled_native_manager(self):
        conn = self.native_fixture()
        selected = self.ready()
        manager = self.modeled_manager(selected)
        with patch.object(S, 'manager_readback', return_value=manager):
            S.bind_manager(self.capsules, selected['capsule'])
            with self.native_modules():
                result = S.inspect_v1(conn, service=self.capsules, capsule_id=selected['capsule'])
                self.assertEqual(result['api'], 'nest.wizard-capsule/1')
                for key in ('complete', 'runtime_coverage_complete', 'resource_coverage_complete', 'lifetime_cpu_enforced'):
                    self.assertFalse(result[key])
                foreign = sqlite3.connect(self.board)
                try:
                    with self.assertRaisesRegex(C.Refused, 'another board'):
                        S.inspect_v1(foreign, service=self.capsules, capsule_id=selected['capsule'])
                finally:
                    foreign.close()


class UnprivilegedProcessTest(unittest.TestCase):
    def test_real_service_guard_refuses_worker(self):
        if os.geteuid() == 0:
            with patch.dict(os.environ, {'HERMES_KANBAN_TASK': 'fixture'}):
                with self.assertRaises(C.Refused):
                    C.service_guard()
        else:
            with self.assertRaises(C.Refused):
                C.service_guard()

    def test_actual_process_exit_and_birth_identity(self):
        child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(10)'])
        try:
            actual = C.process(child.pid)
            self.assertEqual(actual['pid'], child.pid)
            self.assertEqual(actual['context'], C.context())
            child.terminate()
            child.wait(timeout=5)
            with self.assertRaises(FileNotFoundError):
                C.process(child.pid)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_real_independent_process_survives_http_parent_loss_and_kills_exact_child(self):
        # Test-only watchdog, not installed systemd/cgroup enforcement. Its actual
        # process is outside the HTTP parent's group and holds no credentials.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = root / 'watchdog.py'
            helper.write_text('''import os, signal, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-I', '-c', 'while True: pass'], start_new_session=True)
raw = Path(f'/proc/{child.pid}/stat').read_text()
birth = raw[raw.rindex(')')+2:].split()[19]
(root/'ready').write_text(str(child.pid)+' '+birth+' '+str(os.getpid()))
# Independent monotonic deadline survives HTTP launcher exit.
deadline = time.monotonic() + 0.5
while time.monotonic() < deadline:
    time.sleep(0.01)
raw = Path(f'/proc/{child.pid}/stat').read_text()
assert raw[raw.rindex(')')+2:].split()[19] == birth
os.killpg(child.pid, signal.SIGKILL)
result = child.wait(timeout=3)
(root/'exit').write_text(str(result))
''')
            launcher = subprocess.Popen([sys.executable, '-I', '-c',
                'import subprocess,sys; subprocess.Popen(sys.argv[1:], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)',
                sys.executable, '-I', str(helper), str(root)])
            self.assertEqual(launcher.wait(timeout=5), 0)
            deadline = time.monotonic() + 8
            while not (root / 'exit').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((root / 'ready').exists())
            self.assertTrue((root / 'exit').exists(), 'independent watchdog did not settle child')
            pid, birth, watchdog = (root / 'ready').read_text().split()
            self.assertNotEqual(int(watchdog), launcher.pid)
            self.assertTrue(birth.isdecimal())
            self.assertEqual(int((root / 'exit').read_text()), -signal.SIGKILL)
            with self.assertRaises(FileNotFoundError):
                C.process(int(pid))


if __name__ == '__main__':
    unittest.main(verbosity=2)
