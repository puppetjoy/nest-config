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

The managed package pin is `app-admin/nest-cli-0.9.0_p20261021-r5` from
overlay MR !9, merge `0a63bb6c1eb03f15ba91d06d4fc6ff784b8a6890`.
Its complete installed native source aggregate must be
`f368ae1400d0e93ad63fcd07b401a01ba62ecae80d360e55a16ddc664270ecdf`.
The pin is desired state, not proof of installation on every host. Verify the
exact installed revision and source on each intended consumer. Package delivery
does not grant live reboot authority or make an old transaction eligible.

Revision r5 retains native reboot continuity and introduces accounting contract
3 for conservative shared-ancestor finite quota/refquota admission. Historical
contract-2 receipts remain readable/exportable, but cannot authorize a new reboot
or interrupted preparation under contract 3. Do not edit a stored accounting
marker, change its digest or downgrade to bypass refusal. Actual finite-limit
admission and changed-boot lifecycle acceptance remain separate from package
installation and read-only checks.

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

## Native preparation exits

Completed phases must have a null or zero aggregate native exit. Each completed
command must have a true native success flag and a null or zero exit, except
the tagged kernel-phase `puppet` operation also permits detailed exit 2 (changes
applied). The original 2 is retained, never rewritten to zero or confused with
the separate normal-main unchanged-repeat requirement. Exit 2 from copy, module,
mount or other operations, Puppet 1/4/6, and nonzero aggregate phase exits cannot
claim completion or eligibility. Valid failed/stopped phase outcomes remain
exportable. Null remains an unmeasured existing operation outcome, not a measured
process exit. These transported checks do not replace native locked validation.

Older native CLI reboot validation may still reject an otherwise prepared
transaction containing a legitimate kernel Puppet exit 2. Correcting the
supervisor parser alone does not repair installed native eligibility. Verify
reviewed CLI/package delivery separately; never rewrite old receipts, bypass
the native refusal or replay preparation merely to replace a 2 with a 0.

## Observation after disconnect or controller restart

`nest::host::observe_update_reboot` reopens an earlier original-boot receipt from
`check_update_reboot`, then reads exactly `nest reset status ID --format=json` on
one inventory target. It has no execute, preparation retry or acceptance option.
Use it after a separately authorized native request loses its result, or after
the existing external controller resumes. This is observation continuity, not an
implemented external-controller dispatch or complete wave lifecycle.

Supply `target`, `transaction`, `release`, `hostname` and `output_dir` as above,
plus `admission`: the complete returned reboot-plan receipt for the original
prepared boot. The original content-addressed admission file must still exist
in that same canonical supervisor directory. Preserve both file and receipt
across the controller boundary; copying only a path or reconstructing a receipt
from memory is insufficient. If copying to a different execution host, verify
the exact bytes and deliberately update the receipt's path to the same named
file in its new mounted `output_dir`. The digest and byte count cannot change.

    bolt plan run nest::host::observe_update_reboot --params @/absolute/path/reboot-observation.json

Before contacting the host, the task reopens and checks the exact admission
filename, digest, length, context, original boot and eligibility semantics.
It rejects missing/corrupt files, symlinks, cross-directory paths and a receipt
already collected on the changed boot. It reopens admission again during final
publication. A valid status must preserve the original host/pool/BE GUID trees,
shared-state/source/policy identities and every preparation phase. Existing
intent may acquire completion but cannot disappear or change identity; returned
completion cannot change or regress to intent. Native status independently owns
live storage/policy validation, not this supervisor projection.

The sanitized `nest_update_reboot_observation` retains the exact admission handle
and native report. Its `submission_outcome` is one of `not_attempted`, `unknown`,
`returned_success` or `returned_failure`. Separately, `target_boot_observed` is
true only for an observed changed boot on the exact target with unchanged next
selection and a native reboot object. A changed boot without that object cannot
be attributed to this transaction's submission. A returned-success receipt on
the original boot is not a completed boot; an unknown or failed submission can
nevertheless later be observed on the changed target. None of these observations
overrides the original command exit or independently verifies health/acceptance.

`resubmission_allowed`, `execution_requested` and `acceptance_recorded` remain
false in every result. `not_attempted` is not permission to submit: the wave,
window, survivor, retention and external-controller gates remain separate.
Transport refusal, wrong identity/boot, missing observation or failed publication
halts the invocation. A later invocation repeats only read-only observation. Never
retry preparation or reboot to recover evidence, edit intent, clear failures,
or advance another failure-domain wave based on this receipt alone.

### Optional bounded transport reconnect

After a separately authorized request or external-controller restart, callers
may add `reconnect_timeout`, an integer from 5 through 600 seconds. Omission
preserves the immediate single-status-read behavior and its exact result shape.
The plan reopens the original admission before contacting the host, uses Bolt's
existing `wait_until_available` with a five-second retry interval, then reopens
admission again before the single native status read. Missing or changed admission
after waiting stops without a status command. Timeout stops without a second
wait, status acquisition, fabricated report or automatic reboot/preparation retry.
The budget configures Bolt's normal connection loop, not a hard real-time process
kill deadline; underlying inventory transport timeouts still apply.

This retries only ordinary inventory-backed connection establishment. It does not
wait for a disconnect or invoke the reboot plan. A reachable original boot may
return immediately and remains an original-boot observation, not a completed
reboot. A changed boot must still satisfy the exact existing native continuity
checks. Connection success cannot imply target-boot success, health, acceptance,
release permission or permission to submit another request. No credentials,
transport or escalation policy changes, and no direct SSH fallback is added.

Keep the admission file and report directory on persistent external controller
storage across the intended outage. This option does not launch that controller,
dispatch the original reboot, resume an interrupted process, implement waves or
prove actual A/B boot continuity. Those remain separate lifecycle obligations.
Rollback omits the optional parameter; retain all prior observations and intents.
