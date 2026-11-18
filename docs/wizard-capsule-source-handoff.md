# Wizard finite Nest capsule source handoff

## Scope and ownership

This is the first Nest repository source boundary for ^2381, supporting original
Wizard ^2340 (`ar-20261108-214419-0291cd`, task `t_36e33d9d`). The original remains
the only integration and product-acceptance owner. The authoritative contract is
Native commit `7921c99da89211a637dddb7be4462b0b35288c2a`,
`docs/kanban-wizard-runtime-custody-source-report.md`, lines 68–88.

**Supported source boundary, not a complete installed producer.** This source
implements protected prospective selection, retained single-attempt storage
provisioning, independent readback, supervisor binding and cutoff/kill source.
Every complete-admission path still refuses. No merge, installation, mount,
quota/dataset/unit change, operational enrollment, model episode or production
activation is part of this handoff. No production dataset or quota is selected.
Native/Broker source and original history are not edited.

The isolated worktree was fast-forwarded from `185a3bad139004958a0dbbfe75eeba53e39e4489`
to authenticated current main `2b507d71e391c6d07199d7c45e2c2f0a2469192f` before edits,
preserving the accepted Telegram/source repairs and existing runtime pins.

## Implemented source

- `files/app/hermes/wizard_capsule.py`: service guard, strict protected policy,
  canonical board/host/boot selection, image hashing, immutable service ledger,
  serialization, single-attempt provisioning, reconciliation, revocation,
  effective byte/inode mount readback, launch-policy candidate, cgroup reader
  and conservative cutoff decision engine.
- `files/app/hermes/wizard_capsule_supervisor.py`: actual system-manager reader,
  prospective empty-root and independent-supervisor binding, versioned Native
  observer callback, independent watchdog loop source and exact-directory-FD
  kernel subtree-kill source. Successful kill requests never prove reap.
- `manifests/app/hermes/wizard_capsule.pp`: inert root-owned source installation.
  `nest::app::hermes::wizard_capsule_source_enabled` defaults to false. Even true
  only installs the two modules; it creates no state root, policy, identity,
  image, mount, cgroup, service, callback registration or enrollment.
- `spec/files/wizard_capsule_test.py`: isolated source qualification. The existing
  Hermes install fixture CI job explicitly executes this otherwise nondefault
  unittest filename. The public class spec covers default exclusion, explicit
  opt-in inclusion, compilation and install ordering.

## Trust and versioned Native consumer interface

API identifier: **`nest.wizard-capsule/1`**. Policy `schema` is literal integer 1.
The exact policy fields are enforced in `read_policy`; extra fields, duplicate
keys, nonfinite numbers, booleans in integer fields and malformed pins refuse.
There is no JSON receipt-import API, CLI provisioner, worker tool, plugin
self-registration, privilege helper or model credential in either module.

The trusted root service owns the private ledger directory and every ancestor;
policy/image and ancestors are root-owned and not group/world writable.
Contained identities must be dedicated UID/GID values, not root or Joy. The
public selection calls the existing Native service guard and requires its
writer transaction (owned by this operation, with nesting refused), exact connection board device/inode, genuine indexed
request envelope, no original runs and no physical request/unresolved history.
The Native writer lock is held over the service-ledger selection commit. This
is deliberately not a distributed transaction: a Native commit failure may leave a
retained unused selection, never a payload grant or permission to reset it.

| Interface | Meaning |
| --- | --- |
| `Store(directory)` | Root-service-only private SQLite evidence store, separate from the Native board. No Native schema/history writes. |
| `Capsules.select(native_conn=..., policy_path=..., policy_sha256=...)` | Exact prospective selection under Native's existing service writer. Returns retained capsule/root, absolute monotonic deadline, immutable policy/board/context and conditional CPU reserve. Exact repetition retains all values. |
| `Capsules.provision(capsule)` | At most one real storage-creation attempt; selected identity and attempt commit before the syscall. No payload release. Existing bound roots are independently re-read, never recreated. |
| `Capsules.reconcile(capsule)` | Read-only inspection of the same attempted root, including uncertain creation. Reports unknown ownership and never adopts/replays an uncertain effect. A missing or partial root is not evidence of zero consumption. |
| `Capsules.observe(capsule)` | Fresh protected policy/image, host/boot, board and actual mount/statvfs readback against the retained root. Never complete. |
| `bind_manager(service, capsule)` | Bind actual active system-manager units, independent supervisor process and fresh empty zero-CPU/zero-OOM cgroup baseline before population use. Exact repetition retains the baseline; replacement refuses. Does not create or launch units. |
| `inspect_v1(native_conn, service=..., capsule_id=...)` | Service-only callback rechecks Native's actual board/original plus protected selection, fresh image/storage/manager/process/cgroup and retained baseline. Returns explicit false completeness flags and missing gates. No automatic registration. |
| `run_watchdog(service, capsule)` | Source for an independently installed root unit, outside the request subtree. It requires the exact prospectively bound own process, continuously re-reads custody, and requests exact subtree kill on CPU/deadline/OOM/unknown/revocation. It never launches payload or proves kill/reap completion. |
| `Capsules.revoke(capsule)` / `admit(capsule)` | Idempotent retained revocation; complete admission always refuses. |

The inspector result contains `api`, `capsule`, `binding`, `deadline_ns`,
`cutoff`, `storage`, `observed_ns`, `qualification`, `manager`, `baseline`,
`supervision`, `missing`, `complete` and the four explicit false flags
`runtime_coverage_complete`, `request_coverage_complete`,
`resource_coverage_complete`, `lifetime_cpu_enforced`. `binding` includes exact
board path/device/inode, task/request, policy path/digest and host/boot.
`storage.identity` includes root device/inode, mount ID/parent ID, kernel device,
source and host/boot. `manager` includes exact units/invocations/control groups,
actual supervisor PID/birth/executable/context and fresh cgroup identity,
CPU/OOM/population/effective limits. `baseline` is the original cumulative
kernel sample, never a caller-supplied or reset counter.

Native composition must source-pin **both** modules and their installation
origins before importing the callback through its existing trusted integration.
A worker-supplied `service` Python object is not service authority; the root
boundary, protected installation and Native service guard must already exist.
The current source does not claim that this new callback is already registered,
reachable from an installed Native consumer, or compatible with an accepting
complete-seal API. Those are explicit original-owned composition gates, not a
reason to create another wrapper request or wait for whole Wizard acceptance.

## Storage and writable closure

The implemented Linux source backend is an isolated **tmpfs candidate**, not a
production choice and not an implementation of ZFS administration. tmpfs has
independent finite `size` and `nr_inodes` limits observable through real statvfs.
The root is exclusively created under the protected selected parent; the mount
source includes the retained random capsule ID. Readback refuses ordinary
folders, foreign/bind roots, wrong source, changed mount identity, enlarged or
unavailable effective ceilings and incorrect sink ownership/filesystem.
Kernel page rounding must not enlarge the policy ceiling; use a page-aligned
limit when a later authorized isolated installation is qualified.

The candidate root is root-owned and traversable, not worker-writable. Dedicated
worker-owned children map to `/request/work`, `scratch`, `outputs`, `logs`,
`cache`, `artifacts`, `home`. The candidate immutable-image policy directs HOME,
TMPDIR, caches and stdout/stderr there, denies host homes, host networking,
capabilities, namespace changes and cgroup delegation, and makes code/root
read-only. A future selected relay may expose only a bounded AF_UNIX protocol;
third-party credentials stay outside the worker image. Generic source inspection
and diagnostic shell tools belong inside the reviewed image. They are not a
catalog of anticipated recovery cases.

**These unit properties are source intent, not observed containment.** tmpfs
`noexec`, isolated networking and image hashing alone do not deny arbitrary
Python source evaluation or every alternate model route. No payload launcher is
implemented or enabled until the actual immutable image/entrypoint, import/plugin
startup closure, relay protocol, process and denied-route attestations exist.
The observer cannot promote a file inventory into loaded-code containment.

Tmpfs is volatile and charges memory; this phase does not promise durable retained
artifacts across reboot. A separate durable byte/inode-quota backend/export must
be qualified before production use. The feasibility note's dedicated ZFS child
remains an alternative, not a selected parent/dataset or delegated privilege.
Joy's shared `/home/joy` is explicitly excluded as a provisioning parent and no
shared home quota is changed. Reboot invalidates retained selection; no automatic
new root, re-enrollment, cleanup, refund or historical coverage is allowed.

Trusted board/IPC/ledger metadata is separate from request writable storage.
The service ledger caps selection count at 256 and SQLite capacity at 16,384
pages; policy inputs are bounded to 65,536 bytes. A full ledger refuses instead
of pruning history. Native board and future relay metadata retain their own
independent bounded-custody obligations. They are not silently included in the
request tmpfs quota. No destructive cleanup API exists.

## CPU/deadline guarantees and honest refusal

Cgroup CPU rate, memory, zero-swap and task limits are independently read and
compared with the selected values. The managed request root is retained even
when its leader exits; detached descendants remain part of subtree accounting.
A supervisor must be an independent active root-owned system unit outside that
root and its parent/child cgroup hierarchy, not a thread in the HTTP parent.
Missing/replaced/foreign/unknown readbacks never become zero CPU or proof of exit.

The conditional CPU reserve implemented in source is:

```
window = poll_usec + kill_reserve_usec
reserve = (ceil(window / cpu_period_usec) + 2) * cpu_quota_usec
stop_at = cpu_budget_usec - reserve
```

It includes full-period boundary allowance and refuses when reserve consumes the
budget. It is **not a qualified hard aggregate bound**: ordinary Linux does not
guarantee a finite schedule/readback/SIGKILL/reap latency. Hashing the reviewed
image or blocked manager I/O can itself exceed one polling interval. No guessed
latency makes `hard_bound_qualified` true. A second independently installed guard
must stop the request if the watchdog dies; this source does not install it.
`supervise_tick` handles that loss explicitly, while `run_watchdog` cannot detect
its own death. Native must not admit complete coverage until real independent
cutoff/reserve semantics satisfy its contract. A practical finite process
cutoff is not a zero-overrun CPU quota.

OOM, counter regressions, unknown CPU, unresolved kill/reap, replaced unit/root,
revocation and exhaustion remain evidence. Storage attempts and baseline events
are immutable. Concurrent calls serialize with a protected cross-process lock;
exact duplicates do not reset the deadline, create a second root or rewrite the
original Native board. After an uncertain creation, reconciliation observes the
same root only. Recovery to usable authority requires later independently
qualified installed provenance, never adoption based on a writable sidecar or
an expected mount name.

## Qualification and limitations

Run the finite fixture suite with:

```sh
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 spec/files/wizard_capsule_test.py
pdk validate
pdk test unit --tests=spec/classes/nest_app_hermes_spec.rb
```

The source fixtures exercise strict policy/route refusal, public selection and
inspector protocol, real board connection identity, concurrent duplicates,
crashes before/after possible creation, same-root reconciliation, image/policy
revocation, reboot/replacement refusal, immutable/no-replacement history,
modeled byte/inode exhaustion, effective Linux nonquota refusal, candidate mount
argv, fresh manager baseline, modeled CPU/deadline/OOM/watchdog-loss/detached
population, independent watchdog loop unknown/kill evidence and foreign-root
kill refusal. Every capsule case independently compares the untouched original
board bytes, including retained failure/unknown-charge history.

Privilege, protected-path ownership, Native envelope/service guard and
manager/kernel/quota controls are **explicitly modeled** where safe isolated
permissions do not install them. The bounded quota-overrun fixture really writes
at most 16 KiB, but its ceiling is a model, not an installed kernel quota. Real
unprivileged process tests observe PID/birth/context/exit and prove a separate
watchdog process survives its HTTP-like launcher's exit, kills the exact owned
child, waits for its actual signal exit and independently observes process
absence. This is not systemd/cgroup or aggregate-CPU enforcement acceptance.

Retained setup failure: ordinary `pdk validate` and the exact CI-image retry both
refused the inherited ignored authoring lock because it lacked `syslog`. The
untracked incompatible lock was preserved in `.validation-run-capsule/`, without
editing dependencies, shared image or frozen/offline gates. The current CI-pinned
PDK image then bootstrapped its matching lock: validation passed and the focused
class suite passed with 39 examples and no failures. The finite Python suite
passed with 29 tests at that checkpoint. Later exact-source review/CI receipts
must identify their own final immutable head; these checkpoint results do not
claim subsequent edits were tested.

Independent source review first identified the missing same-root reconciliation
reader and insufficient manager/observer source, plus the limits of path-based
mount observations. The candidate adds explicit query-only uncertain-root
reconciliation and actual manager/watchdog/inspector source, preserves admission
refusal and checks root identity around readback. Observation still assumes no
host-root adversary racing mounts; it is not an atomic kernel mount transaction.
Final review must be bound to the actual published bytes.

## Ordinary managed rollout and installed/enrollment plan

**Not executed or authorized for activation in this phase.** Source-ready release
of this dependency does not require completing these later original-owned gates.
There is intentionally no parallel migration controller or automatic installer.
The ordinary executable deployment path is the existing repository Bolt plans.

1. Finish independent exact-source technical review and exact-head CI for this
   draft source MR. Do not merge it in this phase. Hand back the immutable commit,
   full paths, tested files, limitations and CI identity to ^2340.
2. Native composes the callback as a service-only source-pinned integration, not
   a model tool, and qualifies actual board/original/current-envelope ownership
   and its physical ledgers before any accepting complete producer. It must
   implement the payload gate and immutable image/relay/process attestation;
   this Nest phase cannot cross-edit Native or grant its source authority.
3. After separately accepted managed source installation, enable only
   `nest::app::hermes::wizard_capsule_source_enabled: true` through reviewed
   Hiera source. Keep Wizard automatic indexed spending disabled. Audit the full
   noop drift before deciding whether an apply can safely be tag-limited or
   whether ordinary host convergence has other refreshes.
4. From the accepted config project root, the existing commands are:

   ```sh
   bolt inventory show owl --detail --format json
   bolt command run 'id -un && hostname -f' --targets owl --stream
   bolt plan run nest::puppet::deploy
   bolt plan run nest::puppet::run targets=owl noop=true
   # Only after the exact noop/source/availability gate is accepted:
   bolt plan run nest::puppet::run targets=owl
   ```

   These are real repository interfaces, not commands run by this source task.
   Review `plans/puppet/deploy.pp` and `plans/puppet/run.pp` immediately before
   later execution. Preserve ordinary maintenance/refresh custody and inspect
   Puppet's actual report; a zero plan exit alone is not a clean drift receipt.
   Do not use direct SSH or ad-hoc Puppet as fallback.
5. Independently compare installed module bytes/modes/ownership/ancestry with the
   exact accepted source and verify the service's actual system interpreter and
   import origins, without importing user startup paths. Source-only installation
   must produce no mount, quota, unit, policy/enrollment or model execution.
6. A later accepted installed qualification selects a dedicated principal,
   immutable reviewed dependency image and separately quota-backed retained root,
   proves denied routes and safe bounded real byte/inode exhaustion, and installs
   the independent supervisor plus its watchdog-loss guard through ordinary
   source-managed units. No production dataset, parent, quota, principal or image
   is selected by this report. Preserve original unknown/crash evidence. Refuse
   complete admission if a finite cutoff or durable storage contract remains
   unavailable; do not relabel modeled tests as installed enforcement.
7. Only the supervising trusted service prospectively selects an unused original
   population, persists exact host/boot/board/image/policy/attempt identity, creates
   the same root, binds kernel baselines and actual gated launch/process before
   payload release, and invokes installed `inspect_v1` through Native's managed
   integration. Re-read all real facts. Enrollment is not retrospectively applied
   to ^2340's existing work, nor may this child enroll itself or borrow ^2380.
8. Native then owns complete original physical/population/predecessor accounting
   composition; the later genuine Broker accepting checkpoint and real-model,
   Flight Deck and main-chat Telegram acceptance remain original-owned. Keep all
   false flags and indexed automatic-spending refusals until those gates pass.

No original failure, real decision, unknown charge, no-replay fence or canonical
publication is replaced by this source handoff. No product-completion gate is
added to this finite repository source dependency.
