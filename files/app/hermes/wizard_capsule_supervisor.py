"""Source-only independent Nest supervisor/inspector, nest.wizard-capsule/1.

Import beside wizard_capsule, from the future root-managed integration only.
No worker tool, entry point, daemon activation, registration or payload launcher.
All authority comes from root-owned ledger selection plus real manager/kernel
readback. The existing Native integration must source-pin this entire module.
"""
import os
from pathlib import Path
import subprocess
import time

import wizard_capsule as capsule


def manager_readback(selected):
    """Observe the system manager, not a user/caller supplied unit receipt."""
    capsule.service_guard()
    units = (f"hermesrequest{selected['capsule']}.slice", f"wizardwatch{selected['capsule']}.service")
    result = {}
    for unit in units:
        fields = ('Id', 'InvocationID', 'ControlGroup', 'ActiveState', 'SubState',
                  'MainPID', 'User', 'Delegate', 'FragmentPath')
        read = subprocess.run(['/usr/bin/systemctl', '--system', 'show', unit,
                               '--property=' + ','.join(fields)], check=True, timeout=5,
                              env={'PATH': '/usr/bin:/bin', 'LANG': 'C'},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if len(read.stdout) > 16384:
            raise capsule.Refused('bounded manager readback required')
        facts = dict(line.split('=', 1) for line in read.stdout.splitlines() if '=' in line)
        if (set(facts) != set(fields) or facts['Id'] != unit or facts['ActiveState'] != 'active'
                or not facts['InvocationID'] or facts['Delegate'] != 'no'):
            raise capsule.Refused('exact active nondelegated manager units required')
        if unit.endswith('.service'):
            if facts['User'] not in ('', 'root', '0'):
                raise capsule.Refused('watchdog outside worker identity required')
            pid = int(facts['MainPID'])
            if pid <= 1:
                raise capsule.Refused('real independent supervisor process required')
            facts['process'] = capsule.process(pid)
        group = facts['ControlGroup']
        if not group.startswith('/') or '..' in Path(group).parts:
            raise capsule.Refused('canonical manager cgroup required')
        path = Path('/sys/fs/cgroup') / group.lstrip('/')
        if path.resolve() != path or path == Path('/sys/fs/cgroup'):
            raise capsule.Refused('nonroot exact request cgroup required')
        facts['cgroup'] = capsule.cgroup_readback(path)
        result[unit] = facts
    root, watch = (result[u] for u in units)
    rp = Path(root['cgroup']['identity']['path'])
    wp = Path(watch['cgroup']['identity']['path'])
    if rp == wp or rp in wp.parents or wp in rp.parents:
        raise capsule.Refused('supervisor must be outside request subtree')
    return dict(root=root, supervisor=watch, context=capsule.context())


def _identity(observation):
    """Stable unit/root/process anchors, excluding changing CPU/OOM counters."""
    return dict(context=observation['context'],
                root={k: observation['root'][k] for k in ('Id', 'InvocationID', 'ControlGroup')},
                cgroup=observation['root']['cgroup']['identity'],
                supervisor={k: observation['supervisor'][k] for k in ('Id', 'InvocationID', 'ControlGroup')},
                process={k: observation['supervisor']['process'][k] for k in ('pid', 'birth', 'context', 'executable')})


@capsule.serialized
def bind_manager(service, selected_capsule):
    """Retain a fresh baseline before population release; never a launch grant.

    Existing managed integration must already have created the exact empty root
    and independent supervisor. Creation is not inferred from arbitrary JSON.
    No production manager is created or enrolled by importing/calling an observer.
    """
    selected = service._retained(selected_capsule)
    actual = manager_readback(selected)
    prior = [e['payload'] for e in service.store.events(selected_capsule) if e['kind'] == 'manager_bound']
    if prior:
        if _identity(prior[0]) != _identity(actual):
            raise capsule.Refused('manager replaced; prior baseline and unknown custody retained')
        return prior[0]
    root = actual['root']['cgroup']
    if root['cpu_usec'] != 0 or root['populated'] != 0 or root['oom_kill'] != 0:
        raise capsule.Refused('fresh unused request cgroup required')
    state = capsule.supervise_tick(selected, root, root, supervisor_alive=True, now_ns=time.monotonic_ns())
    if state['stop']:
        raise capsule.Refused('selected effective resource limits or deadline unavailable')
    service.store.append(selected_capsule, 'manager_bound', actual)
    return actual


def inspect_v1(native_conn, *, service, capsule_id):
    """Versioned service-only Native callback; no self-registration or enrollment.

    Native must source-pin the callable AND dependency module before import, use
    its existing service-only integration/writer, and compose its own canonical
    task/request and physical ledgers. This callback never returns a complete seal.
    """
    capsule.service_guard()
    from hermes_cli.kanban_wizard_claims import service_guard
    from hermes_cli import kanban_request_usage as usage
    service_guard(native_conn)
    observed = service.observe(capsule_id)
    policy = observed['binding']['policy']
    envelope = usage.current(native_conn, task_id=policy['task_id'])
    if (envelope is None or envelope['request_id'] != policy['request_id']
            or capsule.identity(policy['board_path']) != observed['binding']['board']):
        raise capsule.Refused('canonical original envelope changed')
    # Native's own board identity, not just existence of the selected board file.
    databases = native_conn.execute('PRAGMA database_list').fetchall()
    board = next(row[2] for row in databases if row[1] == 'main')
    if capsule.identity(board) != observed['binding']['board']:
        raise capsule.Refused('Native callback connected to another board')
    actual = manager_readback(service._retained(capsule_id))
    prior = [e['payload'] for e in service.store.events(capsule_id) if e['kind'] == 'manager_bound']
    if not prior or _identity(prior[0]) != _identity(actual):
        raise capsule.Refused('missing or replaced independent manager binding')
    observed['manager'] = actual
    observed['baseline'] = prior[0]['root']['cgroup']
    observed['supervision'] = capsule.supervise_tick(service._retained(capsule_id), observed['baseline'],
        actual['root']['cgroup'], supervisor_alive=True, now_ns=time.monotonic_ns())
    # All existing false flags are explicit; observation is never source acceptance.
    observed.update(runtime_coverage_complete=False, request_coverage_complete=False,
                    resource_coverage_complete=False, lifetime_cpu_enforced=False)
    return observed


def kill_exact_root(root_identity):
    """Kernel subtree kill source; successful write is not proof of reap/exit."""
    capsule.service_guard()
    root = Path(root_identity['path'])
    if Path('/sys/fs/cgroup') not in root.parents or capsule.identity(root) != root_identity:
        raise capsule.Refused('cannot kill a replaced or foreign root')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (root_identity['device'], root_identity['inode']):
            raise capsule.Refused('cgroup changed before kill')
        kill = os.open('cgroup.kill', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            os.write(kill, b'1')
        finally:
            os.close(kill)
    finally:
        os.close(fd)
    return dict(kill_requested=True, reap_proven=False)


def run_watchdog(service, capsule_id):
    """Independent root-manager entry, not callable by contained workers.

    This is callable source for a future system unit. It never launches payload.
    A second manager guard must supervise this unit; that installation remains an
    explicit gate. On every failure retain unknown consumption, request subtree
    kill only by retained identity, and never erase evidence or refund counters.
    """
    capsule.service_guard()
    selected = service._retained(capsule_id)
    prior = [e['payload'] for e in service.store.events(capsule_id) if e['kind'] == 'manager_bound']
    if not prior:
        raise capsule.Refused('prospectively bound manager baseline required')
    baseline = prior[0]['root']['cgroup']
    # Running in the independently bound watchdog, never the HTTP parent/worker.
    actual_process = capsule.process(os.getpid())
    if any(actual_process[k] != prior[0]['supervisor']['process'][k] for k in ('pid', 'birth', 'context', 'executable')):
        raise capsule.Refused('actual independently bound watchdog process required')
    outcome = dict(stop=True, reason='supervisor_unknown', cpu_unknown=True, complete=False)
    try:
        while True:
            # Re-read policy/image/revocation/host/boot on each independent tick.
            service._retained(capsule_id)
            current = manager_readback(selected)
            if _identity(current) != _identity(prior[0]):
                raise capsule.Refused('manager custody changed')
            outcome = capsule.supervise_tick(selected, baseline, current['root']['cgroup'],
                supervisor_alive=True, now_ns=time.monotonic_ns())
            if outcome['stop']:
                break
            time.sleep(selected['binding']['policy']['poll_usec'] / 1000000)
    except BaseException:
        outcome = dict(stop=True, reason='supervisor_unknown', cpu_unknown=True, complete=False)
    finally:
        # Kill first: failure to record cannot silently leave an unbounded worker.
        try:
            killed = kill_exact_root(baseline['identity'])
        except BaseException:
            killed = dict(kill_requested=False, reap_proven=False, kill_unknown=True)
        with service.store.exclusive():
            service.store.append(capsule_id, 'supervision_stopped', dict(outcome=outcome, kill=killed))
    return dict(outcome=outcome, kill=killed, complete=False)
