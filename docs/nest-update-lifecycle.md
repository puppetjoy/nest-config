# Existing Nest host lifecycle

The existing `nest::host::update` now has `mode=lifecycle`. It continues already
prepared native transactions; it never calls reset preparation or the legacy
reboot plan. The default `reboot=false` returns a read-only eligibility preview.
`reboot=true` explicitly requests the reviewed execution, not owner approval.
Source delivery alone grants no live reset, reboot, promotion or restore scope.

## One policy, two execution boundaries

Use one schema-5 `nest_update_wave_policy` for the existing `mode=prepare` and
subsequent `mode=lifecycle`. Schema 5 retains every schema-4 scope, exclusion,
exact kernel, source, failure-domain, preparation-window and backup-hold field.
It adds exactly `lifecycle` with these fields:

- `controller`: exact existing inventory hostname, outside the target scope.
  Run on a surviving machine with working inventory-backed Joy transport, Bolt,
  the ordinary Nest wrapper, existing credentials and a persistent user systemd
  manager. It must survive the selected physical/failure domains as well as the
  named target outages. Inventory names alone cannot discover physical coupling.
- `window`: exact `not_before` and `not_after` UTC timestamps, using the same
  bounded format as the preparation window. This window gates NEW disruptive
  submissions and catalog/canary starts; observation remains possible afterward.
- `impact`: map keyed by every selected hostname, each a nonempty unique array
  of service/outage tokens. Review actual impact, recovery access and the window
  with Joy before the first disruptive exercise. Metadata does not prove consent.
- `rollback`: `keep_previous_be_manual_recovery`.
- `retention`: `keep_backups_and_origins_until_release_retired`. Existing backup
  holds stay in place across all waves, finalization and report delivery. Release
  retirement and hold removal remain an explicit later owner action, not an
  automatic end-of-host cleanup. Ordinary A/B retains the previous accepted BE;
  ambiguous origin snapshots remain. No quota relaxation or pruning is added.
- `acceptance`: exact map keyed by every selected hostname. Each entry has
  `certname`, nonempty `endpoints` using the existing network-health policy,
  nonempty `canaries`, and `historical_failures` (an explicit possibly empty list).

Each canary has exactly `name` and `command`: a unique short name and argv array.
The plan shell-quotes argv, runs it as the ordinary inventory user, bounds its
command timeout to 60 seconds and brackets it with native boot status. Select
actual service/hardware checks; `/usr/bin/true` is useful only in isolated tests,
not as a production canary. Never put secrets in commands. Only exit status and
the command digest are public; stdout is not copied. Physical session/audio/GPU
UX is reported `not_observed` unless independently exercised by the owner.

Each historical failure has exactly `manager` (`system` or `user@UID.service`),
`identity`, a short `rationale`, `evidence_ref` and bare `evidence_sha256`. These
must describe actual retained incident evidence. Every observed failed unit
must match exactly, and every declared disposition must still be observed.
Unavailable buses/incomplete inventories never pass. No counters are cleared,
units masked, TLS weakened, new identities enrolled or historical failures hidden.

Preparation uses its existing complete `preparation` and `release_manifest`.
Lifecycle instead requires `observations`, mapping every selected inventory
hostname to exactly `{ "transaction": "ID" }`, plus existing canonical
`output_dir`. Do not pass preparation or a release manifest to lifecycle.
`reset=true` and `run_puppet=true` remain required. Preparation is a separate
explicit mutation and is never repeated by a continuation. A failed/unknown
preparation anywhere stops before the first reboot submission.

## Execute and resume through native Bolt

Pass a private JSON parameter file, not interpolated shell JSON:

    bolt plan run nest::host::update --params @lifecycle.json --format json

Set `mode` to `lifecycle`, `targets` to the complete exact host list and `reboot`
to false for preview. For separately authorized execution, use `reboot=true` on
the reviewed external controller. The Nest wrapper supplies its actual host name
as `NEST_BOLT_CONTROLLER`; native non-container Bolt uses its own hostname. This
is normal operator coordination, not a new machine attestation subsystem.

All native preparations are checked first. Existing failure-domain waves are
barriers: an affected controller is alone, independent hosts retain bounded
parallelism, and a failed wave prevents the next one. Immediately before a NEW
submission the plan rechecks window, existing backup holds and (for control-plane
members) the existing survivor/quorum/storage/client-route maintenance plan.

A supervisor intent precedes the native `nest reset reboot ID --execute` call.
Native host-local intent separately enforces at-most-once submission. A lost
reply, nonzero return or controller restart leads only to native status observation.
Twelve bounded observations at five-second intervals distinguish a still-live old
boot from the changed target; each connection attempt uses the existing bounded
Bolt reconnect. An unavailable transport stops rather than resetting/rebooting
again. If the target is not observed within this bounded pass, inspect and resume
the SAME invocation and directory. Never create a replacement transaction.

The same plan then calls normal main apply plus one converged repeat, bounded
boot/system/all-operational-user/network collection and the selected canaries.
It reopens exact sanitized receipts on the supervisor, binds target/rollback GUIDs,
release, boot, shared state and ordinary Git configuration version, constructs
native acceptance evidence, and invokes the existing CLI validator under its
host-local lock. Finalization follows accepted live status only. Completed
catalog/canary receipts are reused; an intent lacking its result refuses automatic
replay. Native acceptance/finalization are idempotent for the same evidence/boot.
No extra-BE producer or exceptional cleanup policy is introduced.

## Surviving external dispatch and report delivery

`nest::host::update_dispatch` defaults to `action=inspect`. Supply the exact
`controller`, existing canonical controller `project` checkout, its tested full
`source` Git SHA, and complete lifecycle `params`. The controller checkout must
be clean and match that source. This dispatch currently supports the existing
Nest wrapper's `/modules/nest` mount: params `output_dir` must be
`/modules/nest/.nest-update/POLICY_SHA256`, with targets as the ordered policy host
array. It creates only the selected local `.nest-update/POLICY_SHA256` work area,
never scratch on `/nest/backup`. Ensure the user manager remains running after
SSH disconnect (existing lingering configuration); do not enroll a new service.

Explicit `action=start` writes parameters once and launches the existing Bolt
plan in one native `systemd-run --user` transient unit, named by the policy digest.
It survives the calling agent/process and a target/controller-agent outage, not
a reboot of the external execution host. Repeated start refuses; inspect the same
unit. Explicit `action=resume` requires unchanged parameters, an inactive/failed
unit and no completed lifecycle report, then restarts that same unit. It cannot
interrupt an active run or replay ambiguous native operations. Private Bolt logs
stay on the execution controller. Unit availability is not acceptance.

After actual completion, `action=export` also requires an existing LOCAL
`output_dir`. It follows the completed report's exact receipt graph, copies real
bounded sanitized documents through Bolt task output, checks digests and lengths,
republishes each on the caller and reopens it there. The returned delivery receipt
indexes source paths and destination handles. Original document bytes are kept,
so embedded source paths remain provenance; the delivery map resolves copies.
Private logs, parameter files and credentials are not exported. The final human
runbook/matrix/archive must additionally be attached to the task before completion.

Rollback stops this automation, preserves journals, A/B, backup holds and reports,
and uses explicit supervised native recovery. Do not delete intent files to
manufacture retry permission. Schema 1–4 planning and observation remain supported;
schema 4 preparation is unchanged, but lifecycle execution requires schema 5.

## Verification boundary

Source fixtures exercise collectors, invalid/missing bus observations, native
catalog exits, historical dispositions, persistent intent, failure-wave barriers,
controller restart, dispatcher admission and cross-host report copying. Mock
systemd/Bolt/ZFS results are not live boot, permission or physical-UX acceptance.
The separately authorized selected canary must still prove real generation and
capacity admission, persistent A/B boot continuity, native apply/repeat, service
acceptance, ordinary finalize and final durable handoff. No OS build or production
alias promotion is launched by this plan or its tests.
