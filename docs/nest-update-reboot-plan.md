# Retained read-only native reboot eligibility

`nest::host::check_update_reboot` checks one existing prepared transaction through
ordinary inventory-backed Bolt transport, with escalation only for the native CLI.
It does not prepare, submit a reboot, wait for reconnect, accept, finalize, change
boot selection or repair missing state. There is deliberately no execute parameter.
The existing `nest::host::update` no-reboot default and empty `reboot_eligible`
execution result remain unchanged. Wave execution, controller restart continuity,
release-long retention and the separately Joy-approved live canary remain open.

The native interface was introduced by CLI MR !13, source
`d684a1ef3f74ec5fcab64996e220816d5cfd1f26`, merged as
`f64f45ef29519a414aa8e57d538b7848b0ef8229`. This source review/merge is not package
installation or actual hardware boot acceptance. Older installed CLIs refuse the
new command rather than fall back to a different reboot mechanism. Installing
new CLI bytes can invalidate a transaction's stored policy digest: never bypass
that refusal or rewrite an existing transaction to adopt the new code.

The managed package pin is `app-admin/nest-cli-0.9.0_p20261021-r4` from
overlay MR !8, merge `8e456c3d815b6f5188c328ca038a560f6fe9291a`.
Its complete installed native source aggregate must be
`70b61aeb00d77ef0f118106158731c1c1d7011cb54574b93b6cde95d55e5226d`.
The pin is desired state, not proof of installation on every host. Verify the
exact installed revision and source on each intended consumer. Package delivery
does not grant live reboot authority or make an old transaction eligible.

## Invocation

Pass a private parameter file with exactly one `target` inventory selector,
`transaction`, immutable `release`, exact native `hostname` and existing canonical
supervisor `output_dir`:

    bolt plan run nest::host::check_update_reboot --params @/absolute/path/reboot-plan.json

The plan rejects multiple/empty target sets and recovery-console names. The
supervisor first validates context and output destination without contacting the
host. It then issues only:

    nest reset reboot TRANSACTION --plan --format=json

The `--plan` action creates no native lock, directory or receipt and sends no
reboot request. The supervisor does write a sanitized content-addressed observation
in the deliberately supplied output directory. With the Nest container wrapper,
use a precreated mounted directory under `/modules/nest`; reopen its corresponding
caller-side project file before handing it to Kanban or another execution host.
This is not a claim that every path exists on both sides of a boundary.

## Result and limits

A successful result is a readback-verified receipt with exact transaction,
release and hostname, plus `read_only: true`, `execution_requested: false`,
`acceptance_recorded: false` and one of these paired values:

- `reboot_eligible: true`, `reboot_reason: eligible`: the native CLI observed its
  exact prepared original boot, current/target GUID trees, expected next boot,
  unmounted target, current capacity contract and source/installed-policy binding.
- `reboot_eligible: false`, `reboot_reason: already_requested`: any valid existing
  write-ahead reboot receipt on that same prepared boot. Neither a known failed
  request nor an unknown result permits resubmission.
- `reboot_eligible: false`, `reboot_reason: already_booted`: independently sampled
  changed target boot and expected next selection. This is not host acceptance.

The retained `nest_update_reboot_plan` includes the allowlisted native report.
The native CLI owns storage/source/policy checks; supervisor parsing does not
independently inspect those resources or grant a lease. Eligibility can become
stale immediately. This plan does not evaluate a disruption window, approved
failure-domain wave, serving survivor, recovery route or external controller.
Those gates are required before any separately authorized execution integration.
Unsafe/unknown identity, pending/stopped state, malformed output, failed transport,
missing destination or publication/readback failure halts without retry or fallback.
Previously retained observations are never overwritten to hide a later failure.

## Reboot report compatibility

The common report retainer now validates and preserves the native optional
`reboot` object, including exact keys, schema, original boot, command, strict UTC
calendar timestamps, preparation phase provenance and current accounting-contract
marker. Extra fields, contradictory duplicate keys, booleans disguised as integers,
failed preparation and inconsistent outcomes refuse before publication. Private
command output, exceptions, environment and machine identity are not copied.
The capacity marker is native provenance, not independent capacity verification.

`reboot_requested` is three-valued, separate from preparation and observed boot:

- false with no object: no native recorded attempt; old reports remain supported.
- null with `state: intent`: completion unknown, not false.
- true with `state: returned` and native exit 0: successful systemd submission,
  not a completed boot or health result.
- false with `state: returned` and nonzero native exit: a known failed attempt,
  distinct from no attempt and still forbidden to replay.

Native action exit remains independent: completion rename/readback failure can
leave a reopened returned-success receipt while the action conservatively fails.
Neither the generic retainer nor this read-only plan turns a receipt into action
success, permission to resubmit or independent acceptance. Actual boot facts remain
in `observation`; native acceptance requires a separate changed-target-boot gate.

Finalization retains reboot history and binds the unchanged object across its
before/after reports. An intent cannot disappear, change or be added during
finalization. Old no-reboot reports preserve their existing lifecycle semantics.
Historical export remains possible when old BEs have since changed; export is not
live eligibility. No live reset/reboot was performed by this source integration.
