# Lossless managed Hermes source transitions

## Contract

`vcsrepo` bootstraps the core checkout but no longer moves its revision.
`hermes-source-sync` exclusively owns subsequent ref movement, before every
Puppet-managed core tool overlay, PM verification, installation and UI build.
This is recurring rolling-ref maintenance, not a one-host migration script.

The helper fetches and resolves the desired remote branch on each run. Normal
rolling updates must fast-forward and leave the checkout attached to that branch.
An explicit `git_commit` remains a detached, ancestry-checked rollback/pin control;
legacy tag refs remain detached. Owl normally follows core `nest` and Broker
`origin/main`; app releases do not require a new Nest Config pin.

Only the eleven tool paths explicitly owned by Puppet may be temporarily
uncovered. The helper records exact pre-transition bytes, mode, ownership,
symlink targets and absence in a root-only journal inside the source Git directory.
It then exposes those paths' current Git base, checks out the desired commit,
restores the overlay states, and attaches the rolling branch. Puppet can then
reconcile those overlays to the current catalog's desired content. Independent
untracked tools are neither removed nor stashed. No global reset, forced checkout,
clean, stash or patch retirement is used.

Staged changes, unknown tracked modifications, an in-progress Git operation,
non-fast-forward rolling movement, unresolved refs and untracked checkout
collisions fail closed. Errors after journal creation attempt rollback to the
original HEAD, branch ref and overlays. The original error still fails the Puppet
resource and blocks dependent resources. Recovery failure retains the journal.
A subsequent invocation recovers an interrupted transition before fetching.
A HEAD outside that recorded transaction requires inspection rather than guessing.
The helper serializes its own invocations with `flock`; the rollout must still
quiesce consumers and avoid concurrent external Git/Puppet writers. This is
process-interruption recovery, not a filesystem/power-loss recovery guarantee.

## Isolated validation

Use the owning repository's focused checks and ordinary MR CI. When changing
this installer, choose only the local checks relevant to the delta:

    pdk validate
    pdk test unit --tests=spec/classes/nest_app_hermes_spec.rb,spec/files/hermes_pm_checkpoint_spec.rb
    python3 spec/files/hermes_source_sync_test.py

The mandatory `Hermes install fixtures` CI job includes the source transition
fixtures. No network or production host is needed for those fixtures. They use
real local Git repositories and cover repeated convergence, later rolling
updates, explicit rollback and re-upgrade, unknown tracked edits, staged edits,
unknown untracked collisions, fetch/restore failures, tags, missing refs,
in-progress Git state, and process death before/after checkout and reattachment.
Catalog examples verify the critical bootstrap → sync → overlay/build edges.

The optional production-shaped fixture reads objects from an existing checkout,
creates isolated shared clones, and uses only a local fixture origin:

    HERMES_SOURCE_FIXTURE=/opt/hermes-agent/src python3 spec/files/hermes_source_sync_test.py

It exercises the exact legacy core
`04fe62345b00986e6a1f4d4776296f7c1e82e1ce` → certified core
`8199b2592b3ad4efd5c7ad8fcf861cffc5514b17` transition with the current Nest
Firefox overlay and independent managed tool payloads, repeated convergence,
explicit legacy rollback and re-upgrade. It verifies the overlay snapshots match
at each endpoint. The object source is read only; all checkouts and fetches are
inside the disposable fixture root. This validates Git source convergence, not
an actual host Puppet apply, PM installation or live agent behavior.

## Routine Owl delivery

Merge the app MR after its relevant CI, then run the existing
`bolt plan run nest::puppet::run targets=owl environment=main` when activation
is intended. A merge alone is not a restart instruction. Verify the compiler
revision if Nest Config itself changed; an app-only release should not need a
new config MR or compiler publication. Verify the installed checkout and stamp,
then smoke-check the changed behavior from the actual consumer.

Before merging to a rolling ref, check whether Owl's automatic Puppet timer
can pick up the new revision. If that would require approval for a gateway
interruption, obtain it before merging, not just before a manual apply.

When several approved Broker MRs are shipping as one batch, wait for the
successful pipeline on the final integrated `main` commit before applying.
GitLab may auto-cancel superseded intermediate pipelines; that is not a pass
for those commits. If the timer could run before final CI and the approved
scope allows holding it, record its original state, stop only the timer, and
verify neither the timer nor its service has a queued job. Restore and verify
the original timer state after convergence.

For an authorized Broker-only update on Owl, scope the existing plan with
`tags='["hermes_agent_request_broker_runtime"]'`. Check drift first with
`noop=true`. Verify the installed Broker checkout and stamp, fresh managed
imports, and the four gateway PIDs. The scoped apply can install Broker without
refreshing the gateways; do not add a restart if the change does not need one.

For an authorized Hermes update on Owl, use `tags='["nest::app::hermes"]'`
with the same plan. This tag also covers Broker. When both refs advance, verify
both resulting-ref CI runs, converge Broker with its narrower tag first, then
repeat the Hermes-tagged noop. Stop if it still reports unrelated drift. Verify
both installed revisions and stamps before restoring a held timer.

An installer update can refresh multiple profile gateways even if a Puppet
noop shows only checkout and installer operations: the installer emits refresh
events only during the real run. Check affected gateway/work activity before
apply and use an independent user-manager execution unit if the invoking
session shares a gateway that can restart. Keep any required interruption
authority. If the client loses contact, read back the original Puppet report,
checkout/stamps, and gateway state before deciding whether anything needs
another apply. Never repeat an uncertain transaction just to get a clean exit.

For routine rolled-back changes, revert the app MR and rerun the same managed
apply and smoke check. An exceptional historical exact pin is not the routine
rollback path.

For exceptional rollbacks, inspect both the published source ref and the
compiler environment. Older `rollback_hermes_*` refs can recreate the retired
`hermes-agent-request-moving-tickets` writer, even if the ref is not currently
materialized on the compiler. Do not select a catalog based on its name. Use
verified rollback source that preserves current lifecycle authority and the
installer transition guards. Retain the stop/disable and file-removal rules
until the older rollback paths are replaced or explicitly retired.

## Original rollout handoff

The [original rollout handoff](https://gitlab.joyfullee.me/nest/config/-/blob/2557015261eb67e00458b67c26802b14355a14bf/docs/hermes-managed-source-transition.md#original-rollout-handoff)
records the one-time exact-pin migration and its acceptance criteria. Keep it
as history; do not replay its source pins, activation, or approvals for routine
rolling releases. Use the maintained delivery and rollback guidance above.
