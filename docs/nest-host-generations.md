# Host-local immutable root generations

`nest::host::stage_generation` bridges an existing versioned Stage 3 publication
and the installed CLI's immutable local source contract. It does not build an
OS, promote a release alias, create/mount datasets, prepare an alternate boot
environment, reset, reboot, accept, finalize, restore, prune or change quotas.
The default `check=true` is read-only, including no lock or receipt creation.
This source interface is not release authorization or live lifecycle evidence.

## Managed interfaces

Puppet installs `/usr/libexec/nest/transfer-generation.py` and the existing
Stage 3 aggregate content-identity implementation beside it. The supported
inventory-backed entrypoint is:

```text
bolt plan run nest::host::stage_generation --params @/PATH/params.json
```

The parameter object has `targets`, `policy`, `manifest` and optional `check`
(default true). `manifest` is the complete retained `nest_release_manifest`, not
its validation receipt. Older calls without this object refuse before any host
command. The supervisor validates the full manifest and exact selected host
output, then binds policy runtime release, build token, source path, content
digest and destination to it. A missing unrelated output also refuses; supplying
only a host artifact cannot bypass complete release validation.
Exactly one canonical inventory name must equal `policy.hostname`. Recovery
consoles and qualified controller aliases refuse. Ordinary Joy/Bolt transport
and Bolt root escalation are used; there is no root-SSH fallback. The installed
helper also accepts the exact JSON policy as one positional argument, followed
by optional `--check`. All policy fields are public placement/identity/budget
metadata; never put key bytes, passwords or other secrets in arguments.

NFS presents a different metadata view: it can synthesize `system.nfs4_acl` and
hide `security.capability`. Direct tree copying therefore requires local ZFS;
NFS tree mode refuses before hashing or reserving a transfer. For a publication
accessed over NFS, pass paired plan parameters `archive` and `archive_digest`
(native `--archive` and `--archive-digest`). Reuse the existing private producer
tar and its independently retained SHA256; do not rebuild or export again.
The archive must be an existing root-owned, single-link mode-0600 regular `.tar`
under canonical root-trusted mode-0700 storage, outside source/state/destination.
Opaque archive bytes preserve the producer's xattrs, capabilities and hardlinks
across NFS. The helper checks the pinned archive digest before and after GNU tar
extraction and requires the unchanged full content digest on the local ZFS root
before sealing. It does not weaken or normalize the content identity. The native
started/complete receipts retain the archive path/digest; later `--verify` needs
neither archive nor publication access. Omit archive parameters in verify mode.

`check=false` explicitly copies and seals this one generation. It is a storage
write and potentially significant read/copy load; use the reviewed release's
host, placement, capacity and maintenance scope. It is not implicitly called by
`nest::host::update` or by successful CI. In particular, no actual generation
transfer or disruptive canary is authorized by these examples.

## Exact policy schema 1

The object has exactly these keys; extra/duplicate keys refuse:

- `schema`: integer 1; `kind`: `nest_generation_transfer`.
- `hostname`: canonical lowercase host name, at most 63 characters.
- `host_identity_sha256`: lowercase SHA256 of the exact stable machine-id string
  without newline. The observed hostname and digest must match the target.
- `pool_guid`, `destination_guid`: positive decimal strings. The destination,
  shared transaction state and current A/B root must be in this exact pool.
- `build_release`: existing versioned Stage 3 build token, matching
  `[a-z0-9][a-z0-9._-]{0,127}`.
- `source`: exactly `/nest/releases/BUILD/hosts/HOST`, with the selected build
  and host. This publication must already be accessible via a canonical,
  root-trusted read-only NFS/NFS4 or ZFS mount. No child or stacked mount is
  accepted. This helper never mounts an export or uses `/nest/hosts/HOST`.
- `release`: `sha256:` plus the lowercase 64-character runtime release-manifest
  digest. This is distinct from the build token and from the content digest.
- `content_digest`: exact `sha256:` aggregate returned by the existing Stage 3
  root publisher/checker and bound by the reviewed release. The helper reuses
  the same byte/metadata/xattr/hardlink algorithm, not a new hash dialect.
- `destination`: exactly `/var/lib/nest/generations/HEX`, where `HEX` is the
  runtime release digest without `sha256:`.
- `write_budget_bytes`: positive integer; `physical_reserve_bytes`: nonnegative
  integer. Both are bounded by signed 64-bit integer range; booleans/floats
  refuse. Budgets must come from the reviewed release, not this documentation.

A digest supplied in a policy is a trusted-root/release-owner assertion, not a
signature, proof of remote dataset GUID, or independent discovery of the
relationship between a build root and a runtime release. Actual source bytes
must match that asserted content digest. Release assembly/approval must supply
the correct identities; this helper never invents or promotes them. The Bolt
entrypoint now reconciles those assertions with the complete manifest, but does
not independently verify producer GitLab jobs, the publication dataset GUID or
release approval. The native helper alone remains the low-level trusted-root
interface, not a substitute for the supervisor release binding.

## Explicit prerequisites and capacity boundary

Before invoking the helper, provide the existing shared `/var/lib/nest/updates`
contract: a root-owned mode-0700 exact writable ZFS mount outside all `ROOT`
trees, on the current root's pool, whose `org.nest:host-id` equals the actual
machine-id. The pool and state dataset must each carry that host binding, and
the state dataset must retain the managed `canmount=noauto` startup contract.
Both state and generation datasets must have no other observed mount aliases.
Missing/unsafe state refuses in every mode, including sealed verification;
the helper never repairs properties or mounts to make the check pass.
State must be shared across A/B;
source checks on one boot do not prove the second boot's mount ordering.

The destination must already be an empty exact writable ZFS filesystem with
the selected GUID, positive creation TXG and canonical root-owned ancestors.
It must be outside `ROOT` and separate from the shared-state tree, with no
children, snapshots or origin. It must have `exec=off`, `setuid=off`,
`devices=off`, and `canmount=on`. The four `org.nest:host`, `org.nest:release`,
`org.nest:build-release` and `org.nest:content-digest` properties must be unset.
No parent, filesystem, quota, reserve, boot mount or ownership is provisioned
or repaired by the helper. A populated/reused/partially copied path refuses.
Puppet's reset filter protects the generation mount tree from writing/deletion;
actual A/B mounting and retention still require release integration.

Transfer admission independently checks apparent one-filesystem source size,
native destination `available`, and whole-pool physical free. The write budget
must cover apparent size; logical available must cover the write budget; free
must cover write budget plus physical reserve. Admission is checked again under
the native host transaction lock before copy. These are configured conservative
budgets, not complete allocation bounds or reservations. Metadata, concurrent
writers and native errors can still stop the copy. No rollback deletion,
compression credit, pending freeing, quota relaxation or copying rehearsal is
used to make it fit.

This transfer budget is NOT the CLI's subsequent reset-capacity policy. After
sealing, use the installed native read-only reset planner with the exact sealed
path and a separately reviewed `nest_reset_capacity_policy`. The managed r5
package uses accounting contract 3, which admits only supported conservative
shared-ancestor finite quota/refquota layouts. Other affected finite limits and
nonzero reservations still refuse; contract-2 observations remain historical
readable evidence, not current admission. Nothing in generation transfer relaxes
the native planner's boundary or makes a reset eligible.

## Checked copy, sealing and failure handling

The helper rechecks exact host/pool/boot/current root, shared-state GUID,
destination GUID/TXG/mount closure and source mount identity. It takes the same
nonblocking `.lock` as native transactions; it never unlinks or breaks a lock.
Read-only checking takes no lock and is therefore an observation, not a lease.

Before copy, it atomically publishes mode-0600
`generation-GUID.started` in the shared state directory with fsync/readback.
Files deliberately do not end in `.json`, so native transaction-ID discovery
does not mistake them for CLI transactions. The no-clobber reservation survives
failure. Local ZFS tree copy uses local-path rsync from the mounted publication, preserving
numeric ownership, modes, nanosecond mtime, ACLs, xattrs and hardlinks. There is
no `--delete`, `--inplace`, remote shell, filtering or source modification.

The full source digest (or pinned archive byte digest) is checked before/after copy and the complete destination
digest must match. After pool sync, one checked ZFS set publishes the exact
hostname, runtime release, build token and content digest with `readonly=on`.
Native properties and the actual read-only mount are rechecked, along with the
same GUID/TXG/boot bindings and full sealed digest. Required package, kernel
source and modules paths must resolve inside that root. Only then is
`generation-GUID.complete` atomically published, fsynced and reopened.

The small JSON report binds policy/digest, observed identities and budget
observations. `sealed=true` means this transfer passed, not that reset capacity,
package compatibility, hardware boot, application recovery or acceptance passed.
`reset_authorized` is always false. The Bolt wrapper checks exact returned
policy and read-only/sealed flags; it never retries a failed command.

On any error or interrupted process, retain the filesystem, `.started` and
native state for diagnosis. Property updates, copy and native storage effects
are not atomic with the receipt. Even an empty failed generation cannot be
replayed automatically. A repeat after successful sealing also refuses rather
than toggling writable or recopying. Read the retained `.complete` receipt and
native source status instead. Removing receipts, deleting datasets, renaming a
generation, rolling back storage or restoring live data is not a recovery mode.
Do not supply another GUID/path merely to evade an ambiguous attempt.

Keep the generation immutable and mounted for native preparation/resume and for
the release retention period. Cleanup is not implemented by this producer;
never make it writable or reuse its identity. No live transfer, real ZFS seal,
A/B boot, finite-limit reset admission or fleet acceptance is proven by unit
fixtures. Tests use disposable ordinary directories and fake ZFS observations;
real rsync, hardlinks/xattrs, flock and atomic receipt publication are exercised.

## Read-only verification of a previously sealed generation

Use the same exact policy with `verify_only=true` on
`nest::host::stage_generation`. Leave `check=true` (the default); the plan
also requires the same complete `manifest` in this mode. Manifest validation is
local to the supervisor, so it adds no publication network dependency. The plan
refuses `verify_only=true check=false` before any target command. The installed
helper's corresponding mode is `--verify`, mutually exclusive with `--check`.
Ordinary placement checking and explicit transfer behavior remain unchanged.

This mode validates the sealed local dataset's current host, pool, GUID,
creation TXG, native properties and exact read-only mount, and the current
shared-state dataset/GUID. It securely reopens both root-owned mode-0600,
single-link, canonical and size-bounded `.started`/`.complete` records. Their
policy and policy digest must match, and completion must be exactly the
started record with `sealed=true`. The local root's complete content digest
and required package/kernel/module paths are checked again. Native identity
and both receipts are reopened after the digest read to reject observed drift.

No source-publication mount, directory or network access is required. The
recorded publication mount remains historical transfer evidence, not a newly
verified source observation. A changed current A/B or boot ID since transfer
is allowed only with the same freshly checked host/pool/generation/shared-state
bindings; the report contains the current BE and boot, not stale transfer values.
This permits inspection after a boot change, but is not proof that an actual
A/B switch or startup mounting has been tested.

The JSON kind is `nest_generation_verification_report`, schema 1. It includes
the exact policy, policy digest, current `generation` observation and SHA256 of
the retained complete receipt. `read_only` and `sealed` are true;
`reset_authorized` and `reset_capacity_admitted` are always false. Historical
transfer free-space observations are not republished as current capacity.
Run the separate native reset planner for actual reset-capacity admission.

Verification creates no lock or receipt and performs no copy, property change,
mount, dataset provisioning, cleanup or repair. It neither takes nor breaks a
busy transaction lock: this is a bounded observation, not a lease against later
mutation or authorization to proceed with a reset. Full digest reads can still
be significant I/O. Missing/ambiguous receipts, wrong ownership/mode, links,
special files, changed identities or corrupt content refuse; do not recopy,
relax checks or fabricate a complete receipt to obtain a passing result.

## Supervisor report retention

Executing `check=false` now requires `output_dir`, an existing canonical
directory on persistent supervisor storage. The plan checks that directory
before contacting the target. It never creates directories or uses a remote
host path as evidence that the supervisor received a report. As with transaction
reports, a containerized Bolt caller must use a caller-backed mounted directory,
for example `/modules/nest/rollout-evidence/ROUND`, not an ephemeral container
path. Read-only check/verify calls remain compatible without `output_dir`.

When supplied, `output_dir` changes the successful plan result to an object with
`report` (the native result) and `retained` (the supervisor receipt). The
supervisor validates exact schema, policy hash, mode/outcome, current boot/root,
state/generation placement and bounded byte counts. It retains only known public
identity/outcome fields, omitting raw mount sources/options, arbitrary output
and the full policy. This is not an independent native observation, producer
resource verification, reset-capacity approval or release authorization.

The existing content-addressed no-clobber publisher fsyncs and reopens the exact
JSON. The receipt returns its supervisor path, SHA256, byte count and explicit
readback flag. Repeated identical retention is idempotent; conflicting bytes
refuse without replacement. Before enclosing completion, reopen the caller-side
file, verify its digest/bindings and retain it through the task artifact surface.
The plan cannot prove that an arbitrary directory survives container/host loss.

Transactional preparation supplies optional `binding` with exactly `transaction`,
`policy_sha256` (the wave policy digest, not the generation-policy digest) and
`stage` (`preflight` or `initiation`). This is allowed only with
`verify_only=true` and `output_dir`. The supervisor validates context before
the native command and retains it as `preparation` in both document and receipt;
the plan rejects a lost or changed returned context. Transfer/placement checks
cannot claim this preparation association. Standalone callers omitting binding
retain their existing byte schema and result. Bound reports distinguish stages,
transactions and wave policies but do not assert observation time, native
transaction provenance or a continuing storage lease.

A failed post-transfer retention step fails the plan, but does not undo or
repeat the successful native transfer. Preserve the host's started/complete
receipts and sealed generation. Recover the exact result through read-only
sealed verification and retention; never recopy merely to reconstruct evidence.
Rollback stops using these calls and retains all native and supervisor records.
No real transfer or live generation acceptance is implied by fixture coverage.
