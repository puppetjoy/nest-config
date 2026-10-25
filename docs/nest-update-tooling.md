# Nest update tooling

This implementation is staged under request ^2045. The completed audit ^2036
is the design input, not a new authorization to reset or reboot hosts. Source
publication, installed tooling, and actual boot acceptance are separate facts.
The implementation matrix retained with the request records those boundaries
for R01–R12. No historical missing rollout receipts are reconstructed here.

## Checked reset CLI source

CLI MR !8 merged reviewed source `d54cdd14f020b596b8e8cf924bc16c547103de45`
into main as `d56b83bbc61b4f43cfd15001add110112a1efd74`. Required pipeline
11001 passed. Its actual supported observation commands are:

```sh
nest version --format=json
nest reset --plan --format=json
```

These commands require the new package, not merely a version string of 0.9.0.
The complete library manifest for this source has aggregate SHA256
`6937c534d1b62b20f3059149e7f064c6c559c3aaab6a0902251576274fa9756a`.
Compare the complete reported file map as well as the aggregate. This is content
identity, not a signature. Overlay MR !4 packages that exact merge as
`=app-admin/nest-cli-0.9.0_p20261021::nest`; `nest::base::cli` selects the exact
version rather than a mutable latest package. Packaging CI exercised a real
Gentoo build and compared all 23 library files. Live installed checks remain
pending until their receipts appear in the implementation matrix.

The `nest_cli_package` tag selects only the CLI package definition and its
ordinary package policy resources. Sync the configured Nest overlay before
applying this tag; do not replace the overlay checkout by hand. Use the existing
inventory-backed Puppet plan, then reopen `nest version --format=json` and
`nest reset --plan --format=json`. No reset execution, mount-service restart,
or reboot is needed to install or observe this package. Keep the previous
activation-safe package/binpkg available; the old 0.9.0 archive alone is not a
safe rollback unless its existing exact-version activation patch is retained.

Human output remains the default. JSON execution output does not make an
executing reset read-only. Legacy `--resume` only skips backup; it is not a
transaction recovery command. `--noop` and `--test` are not safe observation
substitutes. Firmware-only reset now explicitly fails as unimplemented.

The planner records physical pool space separately from dataset and ancestor
quota/accounting. Admission remains explicitly unknown: successful observation
is not permission to reset, proof that promotion fits, or permission to remove
quotas, reserves, or rollback data. Shared `/boot` remains an execution side
effect. Use the CLI's `docs/reset.md` for schema 1 and process/native exit rules.
The lifecycle package selected below supersedes this first checked-reset slice.
Release-aware fleet modes remain later integration work, not commands to infer
from the audit's proposed examples.

## Persisted preparation source contract

CLI MR !9 merged source `f13f50936671f8e04d0c5b25da0f9ec6aa2f42a1`
as `6c3e7f3dc7692d5d1c9713c8f35e2e43bb2843ed`. Required pipeline 11029
passed. Its complete library aggregate SHA256 is
`2ef34733c3a40349a3c75353677fe153e5a22ab29cba88e788b0534100595587`
over 26 library files. This preparation slice is included in the lifecycle
package below; a merged source contract is not installed support.

After immutable packaging and provisioning, the source supports preparation
with `--transaction ID --release sha256:DIGEST --root-generation PATH`, exact
`--resume-transaction ID`, and read-only `nest reset status ID --format=json`
and `nest reset report ID --format=json`. Consult CLI
`docs/reset-transactions.md` for the schema and complete validation contract.
Only interrupted root sync is replayable after identity/mount checks; ambiguous
backup, mount, kernel, unmount or activation stops for inspection. Prepared is
not booted, accepted, or finalized. These are not authorization to execute reset.

Before transaction mode can be used, `/var/lib/nest/updates` must be an exact
root-owned mode-0700 mount of a dedicated writable host-local ZFS filesystem
outside ROOT. Its pool must carry `org.nest:host-id` matching the stable machine
ID. Both A and B must mount that same dataset after their private `/var` and
before update clients. Do not provision per-BE state or use a network fallback.
The reset filter excludes the entire state subtree from both copy and deletion,
including legacy reset. That protection alone does not provision shared storage.

The source currently requires one canonical local read-only versioned ZFS root
generation, with no descendants/submounts and `org.nest:release=sha256:DIGEST`.
The publisher must preserve its identity and never make it writable or recycle
it. Mutable `/nest/hosts/HOST` and network-host aliases are refused; there is no
automatic source transfer or fallback. Generation publication, capacity admission,
shared mount provisioning, package installation, and actual A/B boot continuity
are still integration work, not proven by this source merge. Avoid blanket raw
replication or extra capacity rehearsals to satisfy the source contract.

Report export is sanitized stdout, not a remotely usable artifact path. Bolt
must explicitly copy it to the supervisor filesystem, atomically publish it,
reopen it, validate schema/ID/release/phase rows, and retain it before completion.
No historical receipt is recreated by replaying production. Preparation alone
does not prove boot, acceptance or finalize; do not infer those transitions from
`success: true` on a preparation report.

### Supervisor report readback

The shared report publisher opens each canonical output-directory component
without following symlinks, then performs temporary-file creation, exclusive
hard-link publication, unlink and directory fsync relative to that opened
directory. It never replaces an existing content-addressed report. Before it
returns a receipt, it checks that the pathname still names that directory.

Readback opens the report with `O_NOFOLLOW` and `O_NONBLOCK`, requires a bounded
single-link regular file, reads the same opened inode twice and compares its
device/inode, mode, link count, size and timestamps with the final directory
entry. This prevents a pathname-check/open race, avoids blocking on a substituted
FIFO, and refuses observed in-place changes or same-byte inode replacement.
The original-boot reboot admission uses the same bounded reader before host
contact and again during observation publication. Schemas, content-addressed
filenames, mode 0644 and existing successful receipt fields remain unchanged.

Do not hard-link reports when copying them across execution/notification hosts;
copy the actual bytes, verify their digest and retain independent files. Symlink
and hard-link report aliases now refuse even if their current bytes match.
Concurrent modification may conservatively fail rather than produce a receipt;
no retention failure retries a host action or overwrites prior evidence. A
publication failure can leave a complete but unselected report after the native
operation, which is not a successful enclosing lifecycle result. These bounded
readbacks are observations, not filesystem snapshots, storage leases, continued
protection against a privileged writer, or reset/reboot authority. Preserve the
real files through the task artifact surface before worker cleanup.

## Lifecycle package and compatibility

### Host-local shared transaction state

`nest::update_state` is an explicit host opt-in, selected for Owl and Builder1
as the initial amd64 and arm64 tooling hosts. The default is false, including
excluded consoles. This enables storage provisioning, not a reset or reboot.
The `nest_update_state` tag delivers the helper and enabled
`nest-update-state.service`. Offline host
builds install/enable the unit but never provision storage. On a real host the
oneshot runs after `zfs-mount.service` and the selected root's `/var/lib` mount.
It creates only `PARENT/nest-updates`, where the unique current ZFS root is
`PARENT/ROOT/A` or `PARENT/ROOT/B`, and mounts it at `/var/lib/nest/updates`.
The dataset is outside ROOT, writable, `canmount=noauto`, root-owned mode 0700.
The unit is the explicit mount owner; ordinary `zfs mount -al` cannot race it
ahead of private `/var`. No stop or restart unmounts the state.

The helper binds the root pool and dataset to the stable machine identity using
`org.nest:host-id`. Existing mismatched bindings, alien datasets/mounts, unsafe
ancestors, stacked roots, submounts or populated unmounted state paths refuse
without hiding or moving receipts. It never adopts arbitrary existing datasets,
relaxes quotas/reserves, changes boot selection, unmounts, deletes or replays a
transaction. Its private provisioning lock is separate from the CLI transaction
lock and never unlinked. An interrupted empty owned creation may converge on
retry; unsafe populated or mounted permissions require inspection, not repair.
Root-pool placement asserts host-local storage; it is not an independent proof
of the physical block transport or exclusive pool ownership.

`sudo /usr/local/sbin/nest-update-state --check` reads state without creating
directories or locks. A successful check confirms provisioning, not a prepared
transaction. The CLI still refuses a missing immutable generation. Before the
first A/B exercise, both the accepted root generation and retained rollback
must contain the managed unit/helper and enabled boot ordering, or their
boot-time continuity must be provided through an explicitly reviewed path.
Installing this unit on the running BE alone is not proof of that continuity.
No inactive BE is mounted or modified merely to manufacture test evidence.

Rollback disables future clients/host opt-in but retains the dataset, binding,
receipts and installed mount unit until any unresolved lifecycle is resolved.
Removing the Hiera opt-in deliberately does not destroy or unmount shared state.
Real A/B mount continuity remains a separately authorized canary requirement.

CLI MR !10 merged as `84f95665bc46519fb27d1f670a5d28b0d515321c` after required
exact-head pipeline 11036 passed. Overlay MR !5 packages that merge as
`=app-admin/nest-cli-0.9.0_p20261021-r1::nest` (the previous lifecycle revision).
Its complete 28-library-file aggregate SHA256 is
`85ba2dddc1289e3b4ab2fbea1fda628e41491f5a9b88bbea778cd1dde7228d79`.
Required overlay pipeline 11039 and merged-main pipeline 11040 passed. A new
package selection still requires managed installation and installed file-map
readback; CI is not live host acceptance.

This revision includes explicit bound postboot acceptance and safe finalize.
Use its installed `docs/reset-lifecycle.md` contract, not proposed audit flags.
The collector, shared-state mount and immutable generation are prerequisites;
installing the package does not provision them or authorize a reset. A supplied
acceptance document must reflect real collected gates, not operator assertions
invented to move a transaction forward. Finalize retains ambiguous/external
origins and does not claim snapshot retirement or physical reclamation.

Retain `0.9.0_p20261021` as the activation-safe code rollback. Earlier versions
cannot interpret lifecycle receipts: do not downgrade to bypass a failed
transaction, erase state/locks, or replay a legacy reset. The new immutable
revision must not receive the historical exact-version activation patch.

### Capacity-gated immutable revision

The prior capacity revision is `=app-admin/nest-cli-0.9.0_p20261021-r3::nest`
from overlay MR !7, merge `41608b752f9d3ea424453b4d48994ab85b3344be`.
It packages CLI MR !12, merge `fe6271c03d683a0fc8b2c60f9f9b12922580aaf4`.
The complete 30-library-file aggregate SHA256 is
`eeb70b70847c697a5d624d4672ffc7cec08b7d1150839e9e5eb9ab2738022564`.
Read back the installed plan's full source identity, not just its version;
the Ruby version string does not distinguish these immutable revisions.

This revision retains lifecycle/finalize and adds mandatory release, host,
pool and source-bound `--capacity-policy FILE` for new transactions. Read the
installed `reset-capacity.md` and policy schema. The packaged
`reset-capacity-policy.fixture-only.json` is test data, never a live budget.
Ordinary `nest reset --plan --format=json` remains read-only and does not
itself establish transactional admission or allocate a generation.

Native accounting contract 2 inventories the complete pool, including unrelated
swap/fscache volumes, constrained siblings and retained sibling clones. Only the
exact affected filesystem ancestry and reciprocal clone dependencies enter the
logical transfer closure; whole-pool physical gates still include all usage.
Finite affected quota/refquota, affected reservations/volumes and ambiguous clone
dependencies remain unsupported and fail closed. Unrelated constraints are not
permission to relax affected limits or omit physical consumption.
Physical free/slop/reserve, logical availability, source apparent bytes and
promotion bounds are distinct. Do not relax limits or delete rollback to make
admission pass. A real host may correctly remain unsupported after installation.
No operational budgets or host-local source generations are provisioned by
this package pin. Installing tooling is not approval to reset, activate or reboot.

Keep prior immutable packages and receipts. An unresolved capacity-gated
transaction cannot be downgraded to the prior lifecycle revision or retrofitted
with a different policy to bypass refusal. Historical accepted/finalized reports
remain readable; their existence does not prove a new capacity admission.
Historical accounting-contract-1 preparations remain exportable, but r3 and later refuse
to resume their mutations. Do not rewrite old receipts to the new contract.

### Durable native reboot revision

The previous durable reboot revision is `=app-admin/nest-cli-0.9.0_p20261021-r4::nest`
from overlay MR !8, merge `8e456c3d815b6f5188c328ca038a560f6fe9291a`.
It packages CLI MR !13, merge `f64f45ef29519a414aa8e57d538b7848b0ef8229`.
The complete 31-library-file aggregate SHA256 is
`70b61aeb00d77ef0f118106158731c1c1d7011cb54574b93b6cde95d55e5226d`.
Verify the installed full source identity and exact Portage revision; the Ruby
version string alone does not distinguish r3 from r4.

This revision retains capacity accounting contract 2 and the activation-safe
floor. It adds the existing native transaction's explicit at-most-once reboot
interface, documented in `nest-update-reboot-plan.md` and installed
`reset-reboot.md`. The managed pin does not invoke it, enable wave execution,
alter the no-reboot default, provision a generation or authorize disruption.
Use `nest_cli_package` for a narrowly tagged inventory-backed Puppet installation;
package changes alone do not require a host or service restart.

Installing different CLI bytes changes the installed policy digest. Existing
transactions bound to older source may correctly refuse mutation. Preserve their
receipts and inspect them; never rewrite a digest, erase an intent, downgrade to
bypass a refusal or submit another reboot after an ambiguous result. Keep prior
immutable packages for inspected code rollback, not transaction replay.

### Finite shared-ancestor package and report compatibility

CLI MR !14 is accepted as merge
`aaae2dbdc064ca14a46c03344ef4fb80ac507671`, with accounting contract 3.
The previous finite shared-ancestor package is `=app-admin/nest-cli-0.9.0_p20261021-r5::nest`
from overlay MR !9, merge `0a63bb6c1eb03f15ba91d06d4fc6ff784b8a6890`.
The complete 31-library-file aggregate SHA256 is
`f368ae1400d0e93ad63fcd07b401a01ba62ecae80d360e55a16ddc664270ecdf`.
Disposable Gentoo packaging verified the runtime and nine installed documents;
this does not prove managed installation, live capacity admission or boot
acceptance. Verify the installed complete source identity and exact Portage
revision after inventory-backed `nest_cli_package` delivery. The version string
alone remains insufficient. No service restart or reboot is needed.

Contract 3 supports finite quota/refquota only on strict shared ancestors of
both current and target roots. Each finite quota minus native used, each finite
refquota minus native referenced, and every affected available value must cover
the entire write plus promotion budget. Physical reserve/slop, source lower
bound and promotion bound remain independent gates. Affected reservations,
finite BE-root/descendant/source-only limits and unsupported layouts still
refuse. No quota copying, relaxation or rollback reclamation is introduced.
Every preparation boundary rereads accounting; shared ancestor GUIDs and limits
must remain bound, even when a limit increases or becomes unlimited.

The supervisor preflight retainer accepts native accounting contracts 2 and 3,
preserves the observed contract and accounting digest without exporting raw
accounting, and always records `reset_authorized: false`. The report retainer
accepts reboot provenance from either readable contract without converting
command success into boot acceptance. Unknown contracts and noninteger values
refuse. These transport readers do not grant native execution eligibility:
contract 3 CLI can export valid contract 2 history, but cannot resume its
preparation or make it newly reboot-eligible. Never relabel a historical receipt,
replace its bound policy or downgrade to bypass refusal. Actual A/B and finite
limit behavior still require the separately approved disruptive canary.

### Checked kernel Puppet outcomes

`nest::base::cli` selects `=app-admin/nest-cli-0.9.0_p20261021-r6::nest`
from overlay MR !10, merge `d1c339be0a777b90f94ffc487bdb7885c773cdea`.
It packages CLI MR !15, merge `b1952f110d99b5db4b4de7e57d3f5e39392d134a`.
The complete 31-library-file aggregate SHA256 is
`f142e7e2f430854d9bde85bd4dec1cc3be1c3d9e9edb0b4f141830b99c743ead`.
Verify the entire installed source map and exact Portage revision after ordinary
inventory-backed `nest_cli_package` delivery. Package and source CI are not
installed acceptance. No service restart or reboot is needed for this tooling pin.

Successful kernel `puppet` commands preserve native integer exit 2 as applied,
distinct from exit 0 as converged. The complete kernel phase still has aggregate
exit null or zero. Other completed commands cannot claim exit 2; contradictory
completed outcomes fail closed. Historical successful unknown command exits
remain null, not fabricated measured zero. Failed and stopped reports remain
exportable. Native eligibility and transported report readers preserve the same
outcome contract; none turns command success into actual boot acceptance.

Accounting remains contract 3, with readable contracts 2 and 3. The source change
can invalidate preparation bound to older CLI bytes. Keep prior immutable packages,
receipts, shared state and reboot intent. Never rewrite a digest, downgrade to
bypass refusal, or replay preparation or an ambiguous reboot. Actual A/B lifecycle
and the first disruptive canary remain separately owner-gated.

## Fail-closed ZFS startup

`nest` manages the existing activation preflight before `zfs mount -al`:

```ini
[Service]
ExecStartPre=/usr/bin/nest beadm activate
```

There is deliberately no `-` prefix. A failed inactive-tree property write or
promotion must prevent the subsequent automatic mount. The existing CLI
activation-safe implementation is the minimum rollback floor. Do not downgrade
to the old unsafe activation ordering or ignore an activation error to make a
boot appear successful. Preserve the previous accepted BE and inspect failure
before selecting recovery action.

The `nest_cli_safety` tag selects the drop-in and daemon reload, alongside the
existing activation-backport delivery. It does not select the ZFS package,
kernel build, service restart, or a mount operation. From a provisioned project
workspace, the managed delivery/check sequence is:

```sh
bolt module install
bolt inventory show owl --detail --format json
bolt command run 'id -un && hostname -f' --targets owl --stream
bolt plan run nest::puppet::deploy
bolt plan run nest::puppet::run targets=owl tags='["nest_cli_safety"]' --stream
bolt command run 'systemctl show zfs-mount.service -p ExecStartPre -p ExecStart -p ActiveState' --targets owl --stream
```

Review the deploy plan and its current source/environment first. Use ordinary
inventory-backed `joy` transport and Bolt escalation; do not replace it with
root SSH or ad-hoc Puppet. Readback must show `ignore_errors=no` for activation
and the unchanged `zfs mount -al` command. An already active mount service need
not restart, and this sequence must not restart it to manufacture boot evidence.
A daemon reload and parsed service readback do not prove a real reboot test.

## Full Hermes backup publication

The existing `nest::app::hermes::backup` plan accepts `stage_dir` (default
`/var/tmp/nest-hermes-backup`) and `preserve_existing` (default `false`). The
uploaded helper requires `--stage-dir` for capture; direct helper callers must
add it. Prune and legacy-cleanup interfaces are unchanged. A bounded capture
that must retain every existing generation uses `preserve_existing=true`.

Capture and native temporary files live in a private unique local directory.
The helper rejects final-storage staging paths and unknown/network filesystem
types. It verifies full CRC and required shared/profile members locally before
copying verified bytes to a unique hidden final-storage transfer file. SHA256
readback, fsync and no-clobber hard-link publication precede atomic metadata;
the exact receipt is reopened before success or retention. Hidden transfer
files are publication traffic, not working generations. An interruption can
leave a transfer or an archive without metadata: neither is a completed
generation, and the same checkpoint is refused rather than overwritten or
recaptured. Inspect those exact artifacts; do not delete prior good backups.

Hermes MR !86 coordinates native full capture with cron retention/removal
using the actual stores' native/enclosing full-root backup locks. Contended
retention defers until the next save; explicit removal returns failure without
deleting output. This is coordinated live capture, not a simultaneous snapshot
of every mutable file. Existing full-root filters and WAL-safe SQLite semantics
remain native Hermes responsibilities. Publication tests are not proof that
the native fix is installed or that a live backup capture succeeded.

Private ZIPs and JSON metadata stay mode 0600 in the private final directory;
never attach backup payloads or credentials as task evidence. Rollback retains
the previous complete generation and helper. Do not restore live state merely
to validate publication. Old complete metadata without a digest remains
readable; new receipts bind SHA256 as well as byte/member counts.

Hermes MR !87 extends that coordination to process-result retention and native
checkpoint removal. Its deterministic concurrent capture regression failed on
the accepted base; required exact-head pipeline 11106 passed on source
`39748cbe20a9b792d79729f7d79a6eec31f9d4a0`. This closes a distinct observed
process-result deletion path, not just the earlier cron-output retention path.
Genuinely missing selected files still fail capture rather than being omitted.

Owl's managed native source pin includes merge `24f541e4e0a022a76d9e3913968ec59db29cc73d`.
The `hermes_source` tag selects the existing source checkout and exact-pin
verification only: no package reinstall, UI build or service restart. This
source-only delivery is appropriate here because the capture patch changes no
dependencies and the existing install is editable. It is not a substitute for
the normal installer on a new host. Existing gateway/cron processes must still
reload through the normal service lifecycle before their loaded retention code
is covered. Verify those process transitions before the bounded real capture;
do not infer loaded-code identity from a new on-disk checkout alone.

## Durable report export to the supervisor

`nest::host::update_report` reads one existing native transaction and passes its
sanitized JSON stdout to `nest::retain_update_report` on Bolt's `localhost`.
It never prepares, resumes, accepts, finalizes, resets or reboots a host. Supply
the exact expected transaction, release digest and host hostname; the inventory
alias alone is not an accepted hostname assertion. Missing shared state, missing
receipt or failed transport stops collection, not a reason to recreate a cycle.

The plan validates the exact transaction/release/hostname context and existing
supervisor destination before contacting the host. A missing, symlinked or
invalid destination fails without even exporting the native report. This is an
observation, not a capacity or writeability lease: later publication can still
fail. Success requires the returned receipt's exact context and
`readback_verified=true`. A lost directory, failed publication or inconsistent
receipt never retries export or any update phase. Preserve the native report
and retry only this read-only export after diagnosing the destination; never
prepare, accept, finalize or reboot to reconstruct a receipt.

Create a canonical output directory on persistent supervisor storage first.
With the existing Nest container wrapper, `localhost` is the short-lived Bolt
container: use `/modules/nest/rollout-evidence/ROUND` backed by the caller's
project `rollout-evidence/ROUND` directory. An arbitrary container `/tmp` path is
not durable outside that container. The task intentionally refuses missing or
symlinked directories. This plan does not create an artifact service or infer
that a remote path exists on the notification host.

The retained JSON is schema 1, kind `nest_update_retained_report`, with explicit
`cli_schema` 1 or 2. It projects bounded known host, source, state, identity,
policy and ordered native phase/command-exit fields from the CLI export. Unknown
fields, raw command output, environment, exception text and full acceptance
payloads are not copied. It checks expected host/transaction/release bindings,
pool and current/target tree associations, phase order, completeness and outcome
flags. Missing data or a failed command cannot become a prepared outcome.
The CLI's accepted/finalized flags are labeled `cli_accepted` and
`cli_finalized`; `acceptance_independently_verified` remains false. Retaining
the CLI assertion does not validate collector gate artifacts or prove a reboot.

Each observation has a content-addressed filename, preserving previous pending,
failed and successful reports instead of overwriting the only prior receipt.
Publication writes/fsyncs a unique temporary file, publishes with a no-clobber
hard link, fsyncs the directory, reopens exact bytes and parses the retained
report. Identical concurrent copies are idempotent; conflicting existing bytes
fail without replacement. The returned receipt includes exact path, SHA256,
byte and phase counts, host, transaction, release and readback status. Only this
allowlisted projection is mode 0644; private native receipts remain on the host.

Before completing the enclosing workflow, reopen the corresponding caller-side
path, verify the returned digest and bindings, and retain that real file through
the existing task artifact API. This plan proves the producer-to-supervisor
boundary, not the subsequent notification-host copy or terminal transition.
Do not list an ephemeral container path as a Kanban deliverable. Report retention
has no automatic pruning; retain failed evidence and handle future retention
under release policy. Rollback disables this collection plan without altering
the native host transaction or its retained reports.

## Legacy host update safety floor

The existing `nest::host::update` plan still defaults to `reboot=false`.
Preparation failure now aborts the plan before any reboot or post-reboot Puppet
phase. The expired unconditional `--resume` workaround is removed: a failed or
ambiguous reset is never automatically replayed. In a mixed-result invocation,
even successfully prepared hosts stay unrebooted; inspect their receipts before
continuing. Successful preparation does not grant new reboot authority.

This conservative compatibility floor is not the completed transaction-aware
wave scheduler. Release policy, explicit per-host phase modes, reboot continuity,
failure-domain admission and acceptance/report collection remain integration
work. Do not call the legacy plan to test those proposed interfaces. Its plan
regressions execute the actual Puppet plan with Bolt's mock executor and mock
subplans, never real reset or reboot commands.

## Bounded system and actual user-manager observation

`nest::host::update_manager_health target=HOST` is a read-only one-host plan.
It invokes `nest::update_manager_health` through the ordinary inventory-backed
Bolt transport with root escalation, which is required to inventory all actual
user managers and query their buses. It does not prepare, accept, finalize,
reboot, apply a catalog, clear failures, mask units, or start a user manager.

The task emits schema 1, kind `nest_update_manager_health`, an observed boot ID,
system failed-unit identities and each operational `user@UID.service` manager's
UID, PID, availability and failed-unit identities. It cross-checks the complete
loaded user-manager unit inventory against actual `systemd --user` processes,
including lingering managers without a login session. It queries each existing,
ownership-checked user bus as that user, then repeats both inventories and checks
boot continuity. A missing bus, failed command, orphan process, transitioning
manager, changed inventory or unsupported JSON output is unavailable, never zero.
An empty available inventory requires both successful unit and process scans.

System failed-unit inventory is sampled before and after the complete user
collection. Each available user bus is queried again after all initial bus
queries, before the final manager-unit/process cross-check. A changed failed-unit
set, including a disappearance, makes that observation unavailable/incomplete
and the combined result fail. The original sanitized `failures` array remains;
`failures_after` is added when a successful repeat differs. An unavailable
repeat also fails without replacing the initial evidence with an empty array.
No record is automatically explained, reset or cleared. These bounded samples
detect observed turnover, not transient failures between samples, a new incident
with an identical unit/state tuple, or future health. They are not a monitoring
lease, journal-based historical disposition or live acceptance.

Each command is bounded to five seconds within a sixty-second command budget;
inventories are capped at 128 units/managers. Failed observations remain in the
returned report, and all discovered managers are attempted even if one bus fails.
No raw command output, unit descriptions, environment or journal is returned.
Task execution may succeed while the returned `result` is `fail`: callers must
inspect availability, completeness and result, not only Bolt transport success.
Failure to establish basic observation returns a Bolt task error instead.

This is the manager-observation component of acceptance, not complete R11 or
an acceptance document for `nest reset accept`. `acceptance_recorded` is always
false. A zero-failure manager inventory does not prove a responsive desktop or
physical audio/display UX. Retained failed records remain failed here; later
release-policy integration must bind each historical explanation to its exact
unit identity and retained journal/rationale rather than erase or auto-explain it.
Normal main catalog, converged repeat, hardware/service canaries, release policy
and durable collector bundle integration remain required before acceptance.
Rollback simply stops using this observation plan; no host state needs undoing.

The separate [bounded boot identity observation](nest-update-boot-health.md)
adds exact postboot hostname/kernel, unique root/own var, current/next boot and
ZFS GUID/pool-health checks. Neither observation records transaction acceptance;
network/trust, catalog convergence and lifecycle integration remain required.

## Exact Stage 1 and Stage 2 base inputs

The existing `bin/build` wrapper passes optional plan arguments through unchanged.
Stage 1 now accepts `from_image` and `from_image_debug` together; Stage 2 accepts
`from_image`. Explicit overrides must be repository references ending in
`@sha256:` followed by 64 lowercase hexadecimal characters, not mutable tags.
They are shell-quoted at the actual Podman normal/debug initialization commands.
Invalid references, incomplete Stage 1 pairs and overrides with `init=false`
fail before login, container removal, volume removal or creation. An existing
container cannot truthfully claim to have consumed a newly supplied base pin.

Without overrides, compatibility is unchanged: fresh Stage 1 uses Stage 0's
CPU normal/debug pair; refresh uses the selected Stage 1 CPU/variant pair.
Fresh Stage 2 uses the selected Stage 1 CPU/variant debug image; refresh uses
the selected Stage 2 platform/variant image. `refresh` still determines the
ordinary build recipe, including fresh Stage 1 circular-dependency handling;
an explicit pin changes the base, not that recipe. Do not pair unrelated normal
and debug images or use a Stage 2 refresh base with the fresh recipe.

These are build inputs, not read-only planning switches. Real `bin/build` runs
can remove build containers/volumes and compile packages; `deploy=true` still
publishes the existing mutable tags. No OS build or alias promotion is authorized
merely because this interface is installed. The regression suite invokes the
actual Puppet plans using Bolt's mock executor, with build and deploy disabled;
it never runs Podman or mutates storage.

Digest syntax proves neither that the image exists nor that its CPU, variant,
firmware and normal/debug pairing are compatible. The release manifest and CI
consumer must supply and validate those relationships. This slice does not pin
Portage/overlay sync, produce immutable outputs, verify executor identity, publish
versioned Stage 3 roots, or implement the build DAG. Those remain required R06/R07
work. Stage 0's existing `from_image` and Stage 3's existing `stage2_image`
interfaces are unchanged. Rollback stops passing the new optional arguments
while retaining exact accepted base digests; do not rebuild an old release from
mutable tags and call it the same release.

## Plain candidate release manifest

`scripts/nest-release-manifest.py` validates independently frozen inputs,
explicit CPU/platform/variant/host selections, normal/debug output pairs,
executor/producer identities and consumer decisions. Its default is read-only;
optional content-addressed retention reopens exact bytes without changing a
release pointer. See [the implemented record contract](nest-release-manifest.md).
This is not a registry/ZFS verifier, a live release or a wired build DAG.
Stage producers, immutable generation publication and alias promotion remain
integration work. Fixture-only command tests must not be reported as live builds.

## Executor bootstrap failure reporting

Merged-main pipeline 11122 completed successfully on source
`b9b3ab6493cf27ea426fb89bfa76db88b09c8096`, including all three architecture
builds and publication. The published amd64 member
`registry.eyrie/nest/config/main@sha256:693866554c4aaf39f7f78968fa4fb00df6b83acc080cfd36a5f3db406ad83957`
was opened through inventory-backed Bolt without host mounts. Its Git source and
the bootstrap helper, Stage 1/2 plans and release-validator bytes matched that
accepted source. This is executor content verification, not an OS-stage build.

`bin/ci-bolt-module-install` runs the ordinary module installation once. A failed
install now preserves its exact native exit after network/project
diagnostics, and the helper releases its private SSH agent on success, module
failure and key-setup failure. Diagnostics are best effort and cannot turn a
failed module install into success. This fixes Zsh's read-only `status` variable
collision and avoids relying on a returning error trap for exit-time cleanup.
It does not retry module fetches, change credentials or weaken SSH verification.

The all-branch fixture job exercises the actual helper in real Zsh with fake
Bolt, SSH-agent and network commands. Failure exits 1, 37 and 128 must each
produce diagnostics, no installed-success marker, exactly one install attempt
and agent cleanup. These isolated checks do not prove GitLab availability; a
failed real build still needs its own diagnosis and exact-job retry/readback.
Executor publication is distinct from Stage 0–3 builds and live host rollout.

## Stage 1 and Stage 2 candidate output references

The existing Stage 1/2 build plans accept optional `candidate=TOKEN`. Tokens
are lowercase alphanumeric followed by at most 100 alphanumeric/dot/underscore/
hyphen characters. Use a unique pipeline/job/member token, not a stable alias.
Candidate mode requires `build=true`, `init=true`, `deploy=true`, a remote
registry and the exact base arguments described above. Missing requirements
fail before login or container mutation. Default legacy publication is unchanged.

Candidate mode commits and pushes only `candidate-TOKEN` tags in the existing
Stage 1 normal/debug repositories or Stage 2 variant repository. It does not
update CPU/platform tags, aggregate indexes, mirror aliases or a release pointer.
These temporary tags are not immutable or an approval mechanism: retain and
consume the returned content digests, and do not reuse a token for another job.
The plan result is `{normal: REFERENCE, debug: REFERENCE}` for Stage 1 and
`{image: REFERENCE}` for Stage 2, with repository-qualified `@sha256:` references.
Stage 1 returns only after both distinct normal/debug digests are verified;
failure may leave a partial candidate in the registry, never a successful pair.

`files/build/publish-image.sh` uses native `podman push --digestfile`, reading
Podman's newline-free digest file, then reopens the exact remote manifest/config
through explicit `docker://` transport. It creates a unique local verification
index and removes only its owned index. This handles OCI single images (which
the installed `podman manifest inspect` refuses) without repulling all layers.
Push/readback/cleanup failure returns nonzero and no reference; failed create
never removes a possibly preexisting local index. A forced kill can leave an
unselected local verification index. It never changes TLS or credentials.

The publisher verifies manifest/config retrieval, not every layer's readability,
CPU tuning, installed kernel/firmware, source freeze or actual boot compatibility.
The current build recipes still sync Portage/overlay; candidate mode must not be
labeled a frozen release producer until that separate input work is integrated.
Producer/executor identities, member selection and these output references must
still be assembled and retained by the real stage CI lanes. Tools,
versioned Stage 3/local generations, the real DAG and reviewed promotion/rollback
remain unfinished. No new build, candidate push or alias promotion was launched
to test this interface; verification uses real Bash/fake Podman and actual Bolt
plans with a mock executor. A read-only remote OCI metadata probe separately
verified the native Podman path against the accepted executor member.

Rollback stops supplying `candidate`; retain successful candidate digest refs
and previous production aliases. Do not retry an entire OS build to recover a
partial pair without inspecting the existing exact job outcome first.

## Stage 1/2 frozen repository consumption

Both existing plans accept optional `repo_revisions`, a complete hash with
`gentoo`, `nest` and `haskell` full lowercase Git commit SHAs. These correspond
to the existing public Portage snapshot, Nest overlay and Haskell repositories;
Haskell is a real configured input and must not silently float. Pass this hash
through the ordinary JSON Bolt plan parameters. Frozen mode requires `build=true`,
`init=true` and exact base digest arguments (including both Stage 1 bases).
Missing/extra repositories, malformed SHAs, existing-container mode and missing
bases refuse before registry login or any container/volume command.

Frozen mode replaces only the named build container's `CONTAINER-frozen-repos`
volume during initialization, not Stage 1's ordinary `CONTAINER-repos` cache.
The isolated volume mounts `/var/db/repos` with `nocopy`, so image-layer or cached
repositories cannot enter the declared inputs. Never use a live host as the
target of this build helper, or reuse another concurrent job's container name.
This is executing build initialization, not an observation command.

`files/build/freeze-repos.py prepare GENTOO_SHA NEST_SHA HASKELL_SHA` requires
an empty repository directory, fetches each exact commit from its fixed public
origin and checks out detached HEADs. There is no fallback to a branch, mutable
tip or existing cache. A failed fetch leaves partial diagnostic state and fails
the build; it never deletes that state or implicitly retries. Normal plan
initialization on a subsequent explicitly selected build recreates its isolated
volume. `check` with the same arguments performs no fetch or checkout and disables
Git's optional index writes. It verifies complete inventory, exact origin/HEAD,
detached state, clean tracked/untracked/ignored contents and no Git submodules.
`--repos-dir` is available for disposable isolated fixtures, not host adoption.

The plans skip `eix-sync` entirely in this mode and recheck inputs after the
profile catalog and after final configuration/convergence, before publication.
Puppet still owns repository configuration and package policy; it does not get
a new private class parameter or host policy. Any observed drift stops output
publication instead of being silently corrected. Default legacy sync/build
behavior remains unchanged when the hash is absent, including candidate mode
without this new hash. Fresh versus refresh still selects the ordinary recipe.

The JSON helper receipt records the three consumed SHAs; it is not a signature
or full build attestation. Repository volumes are build inputs, not image layers
promised in the published output. Distfiles/binpkg policy, upstream fetches and
other unpinned sources remain distinct reproducibility limits. The release
record now requires the Haskell source as well as Portage/overlay/config. Real
CI producers must still bind this complete selection, exact executor/config/module
identity and resulting digests. Producer records, versioned host roots, promotion
and the repository DAG remain unfinished. No actual OS build or candidate
publication was run for these fixtures.

Pipeline 11125's three architecture builds and executor publication succeeded
at `3ee96818c546104061c8cf39029337931d4adc39`. The amd64 member
`registry.eyrie/nest/config/main@sha256:c4fad1da1c32daca00f052202a1af78397a77dff2c53520609832bc84e3fe7e2`
was opened without host mounts through Bolt; its Git HEAD, Stage 1/2 plans and
publisher bytes matched the accepted source. That previous executor contains
candidate publication, not the new frozen-input interface until its own merged
publication is verified. Rollback stops passing `repo_revisions`; do not call a
mutable-source rebuild the same frozen release or erase earlier build receipts.

## Stage 0/3 frozen repository consumption

The existing Stage 0 and Stage 3 plans also accept the same complete optional
`repo_revisions` hash, using the shared helper described above. Frozen mode
requires `build=true`, `init=true` and a repository-qualified exact base digest:
Stage 0 uses `from_image`; Stage 3 uses `stage2_image`. All repository/base checks
run before container or volume removal. Partial pins, mutable bases, existing
containers and deploy-only calls refuse without entering the build.

Each frozen build recreates only its named `CONTAINER-frozen-repos` volume and
mounts it at `/var/db/repos:nocopy`. Stage 0 no longer uses its legacy repository
cache in this mode; Stage 3 hides inherited image repositories rather than
modifying them in place. Preparation runs before configuration bootstrap. Both
plans skip mutable repository sync and check exact detached clean sources after
profile/configuration and again before output publication. Fetch or drift errors
stop the native plan; they do not trigger implicit retry or cache repair.

Stage 0's frozen path currently supports the existing Git-capable Nest base
workflow, not raw Gentoo bootstrap. The legacy `gentoo` image-name branch refuses
in frozen mode before removal, rather than attempting a floating Git install or
`emerge --sync`. This preserves the old nonfrozen Gentoo bootstrap path unchanged.
The image name is not proof of installed tools: a selected base without the
required Git/Python runtime fails normally; it does not fetch a replacement base.
Stage 0 still derives debug symbols from the same build, not a separately consumed
debug base. Its ordinary `deploy=true` still updates mutable CPU tags unless the
explicit candidate interface described below is selected.

Stage 3's private identity source, remote Puppet environment and rsync destination
are unchanged. Repository pins do not freeze a remote Puppet catalog, verify a
firmware family, or make `/nest/hosts/HOST` immutable. Its ordinary deploy path
still publishes via the existing rsync operation; do not invoke it to test this
interface or label it versioned generation publication. No host reset/reboot,
identity migration or source transfer is performed by the frozen-input helper.

Actual-plan mock regressions cover prerequisite refusal before exact destructive
commands, no sync, isolated volume arguments, two checks, fetch failure, catalog
drift and the legacy path. They are not full package/catalog/OS builds. Together
with mandatory Haskell metadata this completes another R06 input component, not
the real CI producer/DAG, resource verification, immutable roots or promotion.
Rollback stops supplying `repo_revisions`; retained historic manifests without
Haskell remain historical incomplete-input records, not newly accepted releases.

## Stage 0 candidate output references

Stage 0 now accepts the same optional `candidate=TOKEN` as Stage 1/2. It requires
`build=true`, `init=true`, `deploy=true`, a remote registry and a repository-qualified
exact `from_image` digest. A raw Gentoo bootstrap base refuses in this opt-in path;
the existing separate noncandidate bootstrap remains unchanged. Invalid inputs
refuse before registry login, container removal or volume commands.

Only `nest/stage0:candidate-TOKEN` and `nest/stage0/debug:candidate-TOKEN` are
committed/pushed; ordinary CPU aliases and aggregate indexes are untouched.
Use unique pipeline/job/CPU tokens. As for Stage 1, the return value is a map of
`normal` and `debug` exact remote digest references, only after both publications
and manifest/config readbacks succeed. Partial publication fails without returning
a successful pair; equal normal/debug digests also refuse. The shared publisher's
existing failure and owned-cleanup behavior applies unchanged.

Stage 0 consumes only `from_image`: its debug output is derived from that build's
debug volume, not a second consumed base image. The plain release expectations
therefore use `bases: {image: REFERENCE}` for Stage 0, and still require both
output references. Only Stage 1 expectations use a normal/debug input pair. Old
experimental Stage 0 pair-shaped expectations refuse instead of silently
dropping an asserted input. Retain them as historical metadata, not real release
evidence; recreate the independently selected expectations before a new build.

Supply complete `repo_revisions` as well for a source-frozen candidate. Candidate
mode alone does not freeze repository sync or prove executor identity. Actual CI
producer records, complete input/resource verification, Stage 3 catalog/generations,
the multi-project DAG and explicit promotion/rollback remain required. No OS build,
candidate push or alias promotion was performed to test this path. Actual-plan
mock fixtures exercise early refusal, candidate tags, partial push failure,
distinct output pairs and unchanged legacy CPU publication. Rollback stops passing
`candidate`; retain exact output digests and never rebuild merely to recover a
missing receipt.

Executor pipeline 11131 succeeded at
`e6b41cab4ff5496e3cae9c52693c31aa1b64bcf2`. Its amd64 member
`registry.eyrie/nest/config/main@sha256:6830ce237b78d1542370573454240770a1517a6ce626fa69ef83df7d82f4783c`
was opened through inventory-backed Bolt without host mounts/network access inside
the container. Git HEAD and four source-file hashes matched accepted main. This
verifies the preceding frozen-input executor, not this new candidate interface
until its own publication is verified, and is not an OS-stage or boot acceptance.

## Config executor source and pipeline identity

Executor builds now require the exact `CI_COMMIT_SHA`, check out that exact
commit even if its branch has advanced, and set the OCI revision label. The
branch name remains intact for Stage 3's default Puppet environment selection.
The existing candidate publisher returns a remotely verified digest for a unique
pipeline/job/CPU tag. `bin/ci-executor-receipt` checks the actual digest image's
Git HEAD and label using a read-only, network-disabled container without host
mounts, retains the sanitized member JSON as CI artifacts, and validates the
complete same-source/same-pipeline architecture set before index assembly.
Mutable CPU tags no longer select aggregate members. Missing or stale receipts
fail instead of borrowing a newer pipeline's image.

Legacy CPU and `latest` tags remain compatibility outputs and may still move
out of order under concurrent pipelines; they are not release identity or
promotion authority. Stage producer integration and the
multi-project release DAG remain unfinished. See `nest-release-manifest.md` for
the receipt contract and rollback boundary. Fixtures execute the real source
checkout shell against a moving local Git branch and the real receipt CLI with
fake Podman; they do not build an OS or operate on ZFS.

Executor receipt schema 2 adds the consumed exact Bolt base and complete installed
module content identities. CI resolves the pulled base digest before the build;
the nested Nest module is pinned locally to the same config source. The actual
published image must pass a read-only module rehash before its receipt is retained.
Missing/drifted modules and dirty or mismatched Nest sources refuse. This records
actual consumption, not module compatibility or deterministic mutable-ref rebuilds.
Earlier schema-1 receipts remain historical and cannot be mixed into the new
aggregate reader. Release producers still need to bind these identities to the
frozen selection and actual Stage outputs; no OS build is implied by this change.

Pipeline 11145 completed successfully at
`5e537b37d9d8be92609152ba24d4693d2ed216be`, including every architecture and
aggregate publication. Its amd64 digest
`registry.eyrie/nest/config/main@sha256:8f16936971723e721b19fcda563f7914118a9d36e088b8903c0f89d578d6e45b`
was opened through ordinary Bolt without host mounts or container network. Git
HEAD, OCI revision, branch, seven source-file hashes and the nested Nest source
matched accepted main. That verifies the preceding schema-1 executor, not this
new module inventory until its own publication/readback succeeds.

## Operational authority and rollback

The implementation scope permits ordinary source publication, nondisruptive
managed tooling delivery, read-only installed checks, and one bounded normal
backup capture. It does not approve OS-stage rebuilds or release promotion,
fleet resets/reboots, quota relaxation, destructive storage changes, or restore.

Before the first real reset/reboot or destructive canary, present one exact
reviewed host, scope, impact, and rollback proposal to Joy. Preserve console
exclusions and current kernel-qualified exceptions. A separately authorized
canary must verify actual boot/rollback behavior; fixture tests and a successful
merge cannot close that acceptance gap.

Stop on ambiguous phases or unavailable observations. Do not repeat backup,
reset, reboot, or cleanup merely to regenerate evidence. Retain the previous
activation-safe CLI package and source manifest. Rollback of tooling does not
undo shared boot writes or authorize restoring application data.
