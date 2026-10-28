# Lossless managed Hermes source transitions

## Contract

`vcsrepo` bootstraps the core checkout but no longer moves its revision.
`hermes-source-sync` exclusively owns subsequent ref movement, before every
Puppet-managed core tool overlay, PM verification, installation and UI build.
This is recurring rolling-ref maintenance, not a one-host migration script.

The helper fetches and resolves the desired remote branch on each run. Normal
rolling updates must fast-forward and leave the checkout attached to that branch.
An explicit `git_commit` remains a detached, ancestry-checked rollback/pin control;
legacy tag refs remain detached. Main and owl retain their existing rolling `nest`
configuration. No core, broker, extracted-plugin, Firefox or Quill policy pins or
payloads are changed by this repair.

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

Run the standard source and focused catalog checks:

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

## Original rollout handoff

Original rollout ^2206 owns merge, deployment, apply, rollback environment
selection, consumer drain/restart, timer decisions and all live verification.
This source phase must only publish an exact-head, main-targeted MR with green
required CI. Do not replay previously completed activation or broker merges.

Before retrying production, preserve the existing native rollback evidence and
ensure the selected upgrade AND rollback source environments include this
helper/wiring. Merely selecting an old catalog that still uses unsafe vcsrepo
revision movement is not the tested rollback path. The tested source rollback
control is the old core as `git_commit` under `git_ref: nest`, with the helper
retained; legacy runtime/PM settings must also follow the original rollout's
known-good rollback contract. Do not transplant this helper into production
manually or repeat a broad main apply as a diagnostic.

A successful source fixture or CI pipeline does not complete ^2206. Its actual
managed apply, imported-source/dependency parity, model replies, Telegram and
voice/media provenance, dashboard/profile identity, broker lifecycle, credential
writeback, Star browser/tools, Beryl local-only policy, Quill isolation and bounded
stability checks remain the operational owner's acceptance criteria.
