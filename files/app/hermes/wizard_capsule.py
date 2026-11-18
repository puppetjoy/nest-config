"""Nest capsule service boundary, API nest.wizard-capsule/1.

Not a model tool, plugin or enrollment authority. Installation and complete Native
admission are intentionally unavailable in this source phase. Only the trusted
service may invoke mutation methods; no CLI accepts receipts or backend names.
"""
from contextlib import contextmanager
from decimal import Decimal
import fcntl
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time
import uuid

API = 'nest.wizard-capsule/1'
WRITABLE = ('work', 'scratch', 'outputs', 'logs', 'cache', 'artifacts', 'home')
MAX_POLICY = 65536
GATES = ('installed_source_pinned_integration', 'immutable_image_launch_attestation',
         'independent_manager_custody', 'qualified_finite_cutoff_reserve',
         'native_population_and_physical_writer_composition')


class Refused(PermissionError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def service_guard():
    # Unix privilege is the actual boundary, not a secret in worker environment.
    if os.geteuid() != 0 or any(k in os.environ for k in (
            'HERMES_KANBAN_TASK', 'HERMES_KANBAN_RUN_ID', 'HERMES_DELEGATION_ID')):
        raise Refused('dedicated root service outside worker capabilities required')


def protected(path, directory=False):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise Refused('canonical nonlinked protected path required')
    for item in (path, *path.parents):
        info = item.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise Refused('root ownership and nonwritable ancestry required')
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise Refused('wrong protected object type')
    return path


def identity(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise Refused('canonical exact object required')
    info = path.stat()
    return dict(path=str(path), device=info.st_dev, inode=info.st_ino)


def context():
    return dict(host=Path('/etc/machine-id').read_text().strip(),
                boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def process(pid):
    # Missing/permission/parse failures propagate: they are not exit or zero CPU.
    raw = Path(f'/proc/{pid}/stat').read_text()
    fields = raw[raw.rindex(')') + 2:].split()
    executable = identity(Path(f'/proc/{pid}/exe').resolve())
    again = Path(f'/proc/{pid}/stat').read_text()
    if again[again.rindex(')') + 2:].split()[19] != fields[19]:
        raise Refused('process replaced during observation')
    return dict(pid=pid, birth=fields[19], state=fields[0], context=context(), executable=executable)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Refused('duplicate policy field')
        result[key] = value
    return result


def read_policy(path, sha256):
    protected(path)
    if not isinstance(sha256, str) or not re.fullmatch('[0-9a-f]{64}', sha256):
        raise Refused('exact policy digest required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_POLICY:
            raise Refused('bounded regular policy required')
        raw = stream.read(MAX_POLICY + 1)
        after = os.fstat(stream.fileno())
    sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (sig(before) != sig(after) or sig(after) != sig(os.stat(path))
            or hashlib.sha256(raw).hexdigest() != sha256):
        raise Refused('policy changed or revoked')
    value = json.loads(raw, object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(Refused('nonfinite policy')))
    fields = {'schema', 'board_path', 'task_id', 'request_id', 'source_policy_sha256',
              'image_path', 'image_sha256', 'root_parent', 'uid', 'gid', 'bytes', 'inodes',
              'cpu_max', 'memory_max', 'memory_swap_max', 'pids_max', 'cpu_budget_usec',
              'max_seconds', 'poll_usec', 'kill_reserve_usec'}
    if not isinstance(value, dict) or set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise Refused('exact versioned capsule policy required')
    for key in ('image_sha256', 'source_policy_sha256'):
        if not isinstance(value[key], str) or not re.fullmatch('[0-9a-f]{64}', value[key]):
            raise Refused('exact source and image digests required')
    for key in ('task_id', 'request_id'):
        if not isinstance(value[key], str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}', value[key]):
            raise Refused('exact original identifier required')
    for key in ('uid', 'gid', 'bytes', 'inodes', 'memory_max', 'pids_max', 'cpu_budget_usec',
                'max_seconds', 'poll_usec', 'kill_reserve_usec'):
        if type(value[key]) is not int or not 1 <= value[key] <= 2**40:
            raise Refused('finite positive literal limit required')
    if value['uid'] < 65536 or value['gid'] < 65536:
        raise Refused('dedicated capsule identity, not Joy or service identity, required')
    if type(value['memory_swap_max']) is not int or value['memory_swap_max'] != 0:
        raise Refused('zero swap required')
    cpu = value['cpu_max']
    if not isinstance(cpu, list) or len(cpu) != 2 or any(type(v) is not int or not 1000 <= v <= 1000000 for v in cpu):
        raise Refused('finite CPU rate required')
    if value['max_seconds'] > 900 or value['poll_usec'] > 1000000:
        raise Refused('bounded deadline and polling interval required')
    # These are dedicated service paths, never caller-selected shared home quotas.
    root_parent(value['root_parent'])
    protected(value['image_path'])
    identity(value['board_path'])
    return value


def root_parent(path):
    parent = protected(path, directory=True)
    if parent == Path('/') or any(parent == p or p in parent.parents for p in map(Path, ('/home', '/root', '/tmp', '/run', '/proc', '/sys', '/dev'))):
        raise Refused('dedicated retained root parent outside user and volatile trees required')
    return parent


def image_readback(path, expected):
    """Hash the complete image, not a Python file inventory. No launch claim."""
    protected(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        sha = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            sha.update(block)
        after = os.fstat(stream.fileno())
    sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_ctime_ns, s.st_mtime_ns)
    if sig(before) != sig(after) or sig(after) != sig(os.stat(path)) or sha.hexdigest() != expected:
        raise Refused('reviewed immutable image changed')
    return dict(identity(path), sha256=sha.hexdigest(), size=after.st_size)


def cutoff(policy):
    """Conservative conditional rate envelope, NOT a kernel kill-time guarantee.

    One full CFS period at each end plus configured kill latency. The latter is
    an unqualified assumption on ordinary Linux; complete admission stays false.
    """
    quota, period = policy['cpu_max']
    window = policy['poll_usec'] + policy['kill_reserve_usec']
    reserve = ((window + period - 1) // period + 2) * quota
    if reserve >= policy['cpu_budget_usec']:
        raise Refused('CPU reserve consumes the whole lifetime budget')
    return dict(reserve_usec=reserve, stop_at_usec=policy['cpu_budget_usec'] - reserve,
                hard_bound_qualified=False)


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.store.exclusive():
            return method(self, *args, **kwargs)
    return call


class Store:
    """Protected service ledger; never writes the Native board or its history."""
    def __init__(self, directory):
        service_guard()
        self.directory = protected(directory, directory=True)
        path = self.directory / 'custody.sqlite'
        # A private directory prevents foreign precreation of DB/WAL/journal.
        if self.directory.stat().st_mode & 0o077:
            raise Refused('private service ledger directory required')
        if path.exists() or path.is_symlink():
            protected(path)
        self.conn = sqlite3.connect(path, timeout=10, isolation_level=None)
        os.chmod(path, 0o600)
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA max_page_count=16384')
        self.conn.executescript('''
          CREATE TABLE IF NOT EXISTS selections (
            original TEXT PRIMARY KEY, capsule TEXT UNIQUE NOT NULL,
            payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, capsule TEXT NOT NULL REFERENCES selections(capsule),
            kind TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS selection_update BEFORE UPDATE ON selections
            BEGIN SELECT RAISE(ABORT,'immutable selection'); END;
          CREATE TRIGGER IF NOT EXISTS selection_delete BEFORE DELETE ON selections
            BEGIN SELECT RAISE(ABORT,'retain selection'); END;
          CREATE TRIGGER IF NOT EXISTS selection_replace BEFORE INSERT ON selections
            WHEN EXISTS(SELECT 1 FROM selections WHERE original=NEW.original OR capsule=NEW.capsule)
            BEGIN SELECT RAISE(ABORT,'no replacement'); END;
          CREATE TRIGGER IF NOT EXISTS event_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
          CREATE TRIGGER IF NOT EXISTS event_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT,'retain evidence'); END;
          CREATE TRIGGER IF NOT EXISTS event_replace BEFORE INSERT ON events
            WHEN EXISTS(SELECT 1 FROM events WHERE seq=NEW.seq)
            BEGIN SELECT RAISE(ABORT,'no evidence replacement'); END;
        ''')
        self.conn.execute('PRAGMA foreign_keys=ON')

    def append(self, capsule, kind, payload):
        self.conn.execute('INSERT INTO events(capsule,kind,payload) VALUES (?,?,?)',
                          (capsule, kind, encoded(payload)))

    def events(self, capsule):
        return [dict(seq=s, kind=k, payload=json.loads(p)) for s, k, p in self.conn.execute(
            'SELECT seq,kind,payload FROM events WHERE capsule=? ORDER BY seq', (capsule,))]

    @contextmanager
    def exclusive(self):
        service_guard()
        # Open a separate description per operation, including concurrent callers.
        path = self.directory / 'operation.lock'
        fd = os.open(path, os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def close(self):
        self.conn.close()


class Capsules:
    def __init__(self, store, backend):
        self.store, self.backend = store, backend

    def select(self, *, native_conn, policy_path, policy_sha256):
        """Existing Native service guard and indexed envelope are mandatory.

        No supplied envelope/JSON/callback can substitute for this read. Own the
        existing Native IMMEDIATE writer over prospective read/selection commit;
        a caller's deferred read transaction is not a writer lock. No Native row
        changes. Cross-database commit uncertainty retains selection, never release.
        """
        service_guard()
        from hermes_cli.kanban_wizard_claims import service_guard as native_guard
        from hermes_cli import kanban_db as kb, kanban_request_usage as usage
        native_guard(native_conn)
        if native_conn.in_transaction:
            raise Refused('selection must own the Native writer, not nest caller work')
        with kb.write_txn(native_conn):
            native_guard(native_conn)
            policy = read_policy(policy_path, policy_sha256)
            database = next(row[2] for row in native_conn.execute('PRAGMA database_list') if row[1] == 'main')
            if identity(database) != identity(policy['board_path']):
                raise Refused('Native selection connected to another board')
            envelope = usage.current(native_conn, task_id=policy['task_id'])
            if envelope is None or envelope['request_id'] != policy['request_id']:
                raise Refused('genuine exact prospective indexed envelope required')
            used = native_conn.execute('SELECT 1 FROM task_runs WHERE task_id=? LIMIT 1',
                                       (policy['task_id'],)).fetchone()
            usage_facts = usage.snapshot(native_conn, task_id=policy['task_id'])
            if used or usage_facts['requests'] or usage_facts['unresolved']:
                raise Refused('historical population cannot acquire prospective coverage')
            return self._select(policy, policy_path, policy_sha256)

    @serialized
    def _select(self, policy, policy_path, policy_sha256):
        # Internal seam for isolated modeled qualification, not a public API.
        service_guard()
        board = identity(policy['board_path'])
        original = encoded([board, policy['task_id'], policy['request_id']])
        binding = dict(api=API, board=board, policy=policy, policy_path=str(policy_path),
                       policy_sha256=policy_sha256, context=context())
        db = self.store.conn
        db.execute('BEGIN IMMEDIATE')
        try:
            prior = db.execute('SELECT payload FROM selections WHERE original=?', (original,)).fetchone()
            if prior:
                retained = json.loads(prior[0])
                if retained['binding'] != binding:
                    raise Refused('conflicting selection or reboot; no reset')
                result = retained
            else:
                # Detect replacement of the board file: textual scope cannot gain a second root.
                for row in db.execute('SELECT payload FROM selections'):
                    old = json.loads(row[0])['binding']
                    if (old['policy']['board_path'], old['policy']['task_id']) == (policy['board_path'], policy['task_id']):
                        raise Refused('original board identity replaced; retain prior selection')
                if db.execute('SELECT COUNT(*) FROM selections').fetchone()[0] >= 256:
                    raise Refused('trusted metadata capacity exhausted; retain history')
                capsule = uuid.uuid4().hex
                result = dict(binding=binding, capsule=capsule,
                              root=str(Path(policy['root_parent']) / capsule),
                              deadline_ns=time.monotonic_ns() + policy['max_seconds'] * 10**9,
                              cutoff=cutoff(policy))
                db.execute('INSERT INTO selections VALUES (?,?,?)', (original, capsule, encoded(result)))
                self.store.append(capsule, 'selected', dict(cpu_baseline='unknown', released=False))
            db.execute('COMMIT')
            return result
        except BaseException:
            db.execute('ROLLBACK')
            raise

    def _retained(self, capsule):
        service_guard()
        row = self.store.conn.execute('SELECT payload FROM selections WHERE capsule=?', (capsule,)).fetchone()
        if row is None:
            raise Refused('unknown capsule')
        selected = json.loads(row[0])
        binding = selected['binding']
        if context() != binding['context'] or identity(binding['board']['path']) != binding['board']:
            raise Refused('host boot or canonical board replaced; unknown retained')
        policy = read_policy(binding['policy_path'], binding['policy_sha256'])
        if policy != binding['policy']:
            raise Refused('policy revoked')
        image_readback(policy['image_path'], policy['image_sha256'])
        if any(e['kind'] == 'revoked' for e in self.store.events(capsule)):
            raise Refused('capsule revoked; evidence retained')
        return selected

    @serialized
    def provision(self, capsule):
        """At most one storage creation attempt. Uncertain effects are read-only.

        This cannot launch a payload. Mount authority remains in the root service.
        Selection and attempt commit before any external manager/storage call.
        """
        selected = self._retained(capsule)
        db = self.store.conn
        db.execute('BEGIN IMMEDIATE')
        try:
            attempted = any(e['kind'] == 'create_attempt' for e in self.store.events(capsule))
            if not attempted:
                self.store.append(capsule, 'create_attempt', dict(root=selected['root'], cpu_baseline='unknown'))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        if not attempted:
            try:
                self.backend.create_storage(selected)
            except BaseException:
                self.store.append(capsule, 'creation_unknown', dict(root=selected['root'], replay=False))
                raise
        # Never replay create, even if readback says absent after a crash.
        facts = self.backend.storage(selected)
        history = self.store.events(capsule)
        established = [e['payload'] for e in history if e['kind'] == 'storage_bound']
        if established and established[0]['identity'] != facts['identity']:
            raise Refused('quota root or mount replaced; no adoption')
        if not established:
            # In unknown creation the backend must prove unique exact requested
            # mount source, empty tree and service ownership, not merely a path.
            if attempted:
                raise Refused('uncertain creation requires separate installed ownership reconciliation; no adoption')
            self.store.append(capsule, 'storage_bound', facts)
        return dict(api=API, selected=selected, storage=facts, complete=False, missing=list(GATES))

    @serialized
    def reconcile(self, capsule):
        """Query the SAME retained root after uncertain creation, never adopt it.

        A missing/partial root is retained as unknown, not proof of noncreation or
        permission to replay. Installed independent ownership reconciliation may
        later qualify custody; this source observer cannot mint that authority.
        """
        selected = self._retained(capsule)
        if not any(e['kind'] == 'create_attempt' for e in self.store.events(capsule)):
            raise Refused('no retained creation attempt')
        try:
            facts = self.backend.storage(selected)
        except (OSError, Refused):
            facts = None
        return dict(api=API, capsule=capsule, root=selected['root'], storage=facts,
                    ownership='unknown', replay=False, complete=False)

    @serialized
    def observe(self, capsule):
        selected = self._retained(capsule)
        facts = self.backend.storage(selected)
        bound = [e['payload'] for e in self.store.events(capsule) if e['kind'] == 'storage_bound']
        if not bound or bound[0]['identity'] != facts['identity']:
            raise Refused('unbound or replaced storage root')
        return dict(api=API, capsule=capsule, binding=selected['binding'], deadline_ns=selected['deadline_ns'],
                    cutoff=selected['cutoff'], storage=facts,
                    observed_ns=time.monotonic_ns(), qualification=self.backend.qualification,
                    complete=False, missing=list(GATES))

    @serialized
    def revoke(self, capsule):
        service_guard()
        if not self.store.conn.execute('SELECT 1 FROM selections WHERE capsule=?', (capsule,)).fetchone():
            raise Refused('unknown capsule')
        if not any(e['kind'] == 'revoked' for e in self.store.events(capsule)):
            self.store.append(capsule, 'revoked', dict(released=False, cleanup=False))

    def admit(self, capsule):
        self.observe(capsule)
        raise Refused('complete admission unavailable: ' + ', '.join(GATES))


class LinuxStorage:
    """Real privileged tmpfs byte/inode provisioner source. NEVER auto-installed.

    tmpfs is a candidate bounded scratch backend, not a selected production ZFS
    dataset and not durable artifacts. A boot change permanently refuses this
    selection. Installed retention/export and manager gates remain mandatory.
    """
    qualification = 'uninstalled-linux-source'

    @staticmethod
    def create_storage(selected):
        service_guard()
        p, root = selected['binding']['policy'], Path(selected['root'])
        protected(root.parent, directory=True)
        root.mkdir(mode=0o700)  # Exclusive; existing directories are not adopted.
        source = 'wizard-' + selected['capsule']
        options = f"size={p['bytes']},nr_inodes={p['inodes']},uid=0,gid=0,mode=0711,nosuid,nodev,noexec"
        subprocess.run(['/bin/mount', '-t', 'tmpfs', '-o', options, source, str(root)],
                       check=True, timeout=10, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'},
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # No unmount/destroy on partial failure; the exact attempt is retained.
        for name in WRITABLE:
            target = root / name
            target.mkdir(mode=0o700)
            os.chown(target, p['uid'], p['gid'])

    @staticmethod
    def storage(selected):
        service_guard()
        p, root = selected['binding']['policy'], Path(selected['root'])
        protected(root, directory=True)
        before = identity(root)
        # mountinfo is read in this service's real namespace. No caller sidecar.
        matches = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            left, right = line.split(' - ', 1)
            a, b = left.split(), right.split()
            if a[4] == str(root):
                matches.append((a, b))
        if len(matches) != 1:
            raise Refused('one exact real quota mount required')
        a, b = matches[0]
        if b[0] != 'tmpfs' or b[1] != 'wizard-' + selected['capsule'] or a[3] != '/':
            raise Refused('wrong quota filesystem, source or bind root')
        if not {'rw', 'nosuid', 'nodev', 'noexec'} <= set(a[5].split(',')):
            raise Refused('quota mount isolation options changed')
        v = os.statvfs(root)
        effective_bytes = v.f_blocks * v.f_frsize
        # Kernel rounds size to pages; refuse a larger effective ceiling.
        if not 0 < effective_bytes <= p['bytes'] or not 0 < v.f_files <= p['inodes']:
            raise Refused('effective finite byte/inode limits unavailable or enlarged')
        for name in WRITABLE:
            target = root / name
            info = target.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != p['uid'] or info.st_gid != p['gid']
                    or info.st_dev != root.stat().st_dev or info.st_mode & 0o077):
                raise Refused('writable sink ownership or same-filesystem identity changed')
        if identity(root) != before:
            raise Refused('quota root changed during readback')
        return dict(identity=dict(root=before, mount_id=a[0], parent_mount_id=a[1],
                                  source=b[1], device=a[2], context=context()),
                    byte_limit=effective_bytes, inode_limit=v.f_files,
                    bytes_available=v.f_bavail * v.f_frsize, inodes_available=v.f_favail,
                    writable=list(WRITABLE), durable=False)


def launch_properties(selected):
    """Reviewed candidate unit policy, NOT an executor or installed attestation.

    Image must include all runtime/dependency/startup code. /request is noexec;
    source inspection and generic shell tools reside in the immutable image.
    No host home, /tmp, provider credentials, host network or writable code mounts.
    A future relay is a selected AF_UNIX IPC endpoint, never an SDK credential.
    """
    p = selected['binding']['policy']
    return dict(RootImage=p['image_path'], RootImageOptions='root:ro',
                User=str(p['uid']), Group=str(p['gid']), PrivateNetwork='yes',
                RestrictAddressFamilies='AF_UNIX', PrivateDevices='yes',
                ProtectSystem='strict', ProtectHome='yes', NoNewPrivileges='yes',
                CapabilityBoundingSet='', RestrictNamespaces='yes', Delegate='no',
                ProtectControlGroups='yes', ProtectKernelTunables='yes', ProtectKernelModules='yes',
                ProtectKernelLogs='yes', ProtectClock='yes', LockPersonality='yes',
                RestrictSUIDSGID='yes', KillMode='control-group', SendSIGKILL='yes',
                BindPaths=f"{selected['root']}:/request:norbind", ReadWritePaths='/request',
                Environment='HOME=/request/home TMPDIR=/request/scratch XDG_CACHE_HOME=/request/cache PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1',
                StandardOutput='append:/request/logs/stdout', StandardError='append:/request/logs/stderr',
                MemoryMax=str(p['memory_max']), MemorySwapMax='0', TasksMax=str(p['pids_max']),
                CPUQuota=str(Decimal(p['cpu_max'][0]) * 100 / Decimal(p['cpu_max'][1])) + '%',
                CPUQuotaPeriodSec=str(p['cpu_max'][1]) + 'us',
                RuntimeMaxSec=str(p['max_seconds']))


def cgroup_readback(path):
    path = Path(path)
    root = identity(path)
    values = {}
    for name in ('cpu.stat', 'memory.events', 'cgroup.events'):
        values[name] = {key: int(value) for key, value in
                        (line.split() for line in (path / name).read_text().splitlines())}
    limits = {name: (path / name).read_text().strip() for name in
              ('cpu.max', 'memory.max', 'memory.swap.max', 'pids.max')}
    if identity(path) != root:
        raise Refused('cgroup replaced during observation')
    return dict(identity=root, context=context(), cpu_usec=values['cpu.stat']['usage_usec'],
                oom_kill=values['memory.events']['oom_kill'],
                populated=values['cgroup.events']['populated'], limits=limits)


def supervise_tick(selected, baseline, observed, *, supervisor_alive, now_ns):
    """Independent manager's pure decision engine. No reset/refund or kill claim.

    The installed manager must run it outside the worker cgroup, retain the root
    after leader exit and kill the entire subtree. Loss needs a second independent
    manager fail-closed guard. Ordinary Linux provides no finite SIGKILL latency.
    """
    if not supervisor_alive:
        return dict(stop=True, reason='watchdog_loss', cpu_unknown=True, complete=False)
    if (observed is None or observed['identity'] != baseline['identity']
            or observed['context'] != baseline['context'] or observed['context'] != selected['binding']['context']
            or observed['cpu_usec'] < baseline['cpu_usec'] or observed['limits'] != baseline['limits']):
        return dict(stop=True, reason='identity_or_cpu_unknown', cpu_unknown=True, complete=False)
    p = selected['binding']['policy']
    expected = {'cpu.max': ' '.join(map(str, p['cpu_max'])), 'memory.max': str(p['memory_max']),
                'memory.swap.max': '0', 'pids.max': str(p['pids_max'])}
    if baseline['limits'] != expected:
        return dict(stop=True, reason='unselected_limits', cpu_unknown=True, complete=False)
    used = observed['cpu_usec'] - baseline['cpu_usec']
    reason = None
    if observed['oom_kill'] > baseline['oom_kill']:
        reason = 'oom'
    elif now_ns >= selected['deadline_ns']:
        reason = 'deadline'
    elif used >= selected['cutoff']['stop_at_usec']:
        reason = 'lifetime_cpu'
    return dict(stop=reason is not None, reason=reason, cpu_unknown=False,
                cpu_used_usec=used, descendants_present=bool(observed['populated']),
                reap_proven=False, complete=False)
