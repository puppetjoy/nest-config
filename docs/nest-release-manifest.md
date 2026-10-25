# Plain Nest candidate release records

`scripts/nest-release-manifest.py` is a Python 3 standard-library consumer of
independently frozen release expectations and producer result records. It checks
exact inputs/member closure and can retain one content-addressed JSON manifest
in an existing CI artifact directory. It never builds images, queries GitLab or
a registry, copies a host root, changes an alias, or authorizes rollout.

This is part of R06, not completed R06/R07 delivery. The opt-in producer below
executes frozen Stage 0/1/2 and explicitly placed local Stage 3 candidate plans.
Stage 0/1/2 CI invokes the adapter; Stage 3 CI integration remains disabled. The real
multi-project DAG, registry resource verification, output publication and alias
compare-and-swap remain separate integration work. `plans/build/manifest.pp`
still means an OCI multi-architecture index; it is not this release manifest.

## Command contract

From the repository root:

```sh
python3 scripts/nest-release-manifest.py \
  --expectations /absolute/path/expectations.json \
  --candidate /absolute/path/candidate.json
```

The default is read-only. Exit 0 means the submitted metadata reconciles with
those exact expectations. Exit 1 means invalid/unreadable input or failed artifact
retention; stderr contains a bounded error without input values or traceback.
Argument errors use argparse's ordinary exit 2. The validator does not interpret
shell code or fetch references from submitted records.

To retain the manifest, first provide an existing canonical absolute directory
on durable caller storage, then append `--output-dir /absolute/artifact/dir`.
A filename `release-<SHA256>.json` binds exact canonical manifest bytes. Publication
uses a unique temporary file, fsync, a no-clobber hard link, directory fsync and
exact byte readback. An identical concurrent writer is idempotent. A conflicting
file or symlink refuses without replacement; publication does not advance any
release pointer. Failed readback must not be treated as successful retention.
The directory is trusted local CI/supervisor storage, not an adversarial shared
writable directory or a network-publication protocol. An interruption may leave
a hidden temporary file, never a selected production release.

Stdout is one schema-1 `nest_release_manifest_validation` receipt containing the
release name, manifest and expectations digests, member count, optional path and
readback status. `resource_verification` is always `not_performed` and
`promotion_authorized` is always false. CI must retain the actual named file via
its artifact configuration; an executor-local path alone is not artifact delivery.
Before using it elsewhere, reopen the copied manifest and verify the digest.

## Expectations schema 1

The top-level fields are exactly:

- `schema`: integer 1; `kind`: `nest_release_expectations`.
- `release`: lowercase name, starting with an alphanumeric character, followed
  by alphanumeric, dot, underscore or hyphen; maximum 128 characters.
- `sources`: map of exact `nest/...` project paths to lowercase 40-hex Git SHAs.
  Config, overlay, Gentoo Portage and `nest/gentoo/haskell` are mandatory. Each
  selected producer's project must also be present. Branch names, tags and short
  SHAs are not pins. Earlier schema-1 expectation records that omitted Haskell
  are now rejected: retain those historical records, but do not silently add a
  current Haskell tip and call their original input closure complete.
- `executor`: exactly `source` and `image`. Source must equal `sources` entry
  `nest/config`. Image must be a repository-qualified OCI `@sha256:` reference
  with 64 lowercase hexadecimal digits. It records expected executor identity,
  not a proof that an image was built from that source.
- `members`: nonempty independently selected array, bounded to 1,024 rows.
- `consumers`: explicit project classification array, bounded to 128 rows.

Each member has exactly these fields:

| Field | Contract |
|---|---|
| `id` | Unique release-local lowercase token, same syntax as release |
| `stage` | `stage0`, `stage1`, `stage2`, `stage3` or `tool` |
| `project` | Corresponding `nest/stageN` or a selected `nest/tools/...` project |
| `cpu`, `variant` | Explicit lowercase tokens, never aggregate-index guesses |
| `platform` | Required token for Stage 2/3; null otherwise |
| `host` | Required token for Stage 3; null otherwise |
| `mode` | Explicit `fresh` or `refresh`, not inferred from the base name |
| `bases` | Stage 1: exact `normal` and `debug` image pins; all others, including Stage 0: exact `image` pin |
| `compatibility` | Stage 2/3: exact `kernel`, `modules_abi`, `firmware`, `bootloader` strings; otherwise empty object |
| `identity_root` | Stage 3: canonical absolute private identity input directory; otherwise null |
| `identity_reference` | Stage 3 only: exact completed private generation UUID v4; directory basename must match |
| `identity_ca_sha256` | Stage 3 only: reviewed public CA PEM digest, bare lowercase 64-hex |

The last two fields are required only on Stage 3 members and prohibited on all
other stages. Earlier experimental Stage 3 records lacking either field refuse;
do not retrofit them with the current mutable identity or automatically trust its
CA. Re-freeze expectations after independently selecting a completed private
generation and reviewed CA pin. References must be distinct per host member.
These fields are copied into the exact output member and participate in the
canonical expectations digest; a changed reference or CA invalidates the output.
Metadata validation does not open the private tree or establish CA approval.
The producer must run private-generation admission against those exact values.

Selection tuples `(stage, project, cpu, platform, variant, host)` must be unique.
Stage 0 consumes one base and derives both normal/debug outputs from the same
build. Only Stage 1 consumes a base pair. Earlier experimental schema-1 records
with a Stage 0 base pair are rejected rather than silently discarding a claimed
input. Recreate expectations from the actual selected base and bind the new
canonical digest; retain old records as historical metadata, not accepted builds.
Both stages still require distinct normal/debug output references.

Stage 3's publication root is `/nest/releases/RELEASE/hosts/HOST`, distinct from
its private identity tree; equal, ancestor and descendant overlap all refuse.
This is the versioned publication destination, not the transaction CLI's required
host-local read-only ZFS generation. The later transfer/admission producer must
verify ownership, content, local mount, dataset GUID and release properties.

### Read-only Stage 3 publication-root admission

`files/build/check-stage3-root.py` implements resource admission for an already
completed, sealed root. Run it as root on the publication host, not an NFS client:

```sh
python3 files/build/check-stage3-root.py \
  /nest/releases/RELEASE/hosts/HOST HOST RELEASE DATASET_GUID \
  sha256:EXPECTATIONS_DIGEST
```

The path must match exactly and have canonical root-owned ancestors without
group/other write access. Native ZFS inspection must identify exactly one mounted,
read-only filesystem at that path, with the supplied GUID, no descendant
filesystems, `org.nest:build-release=RELEASE` and
`org.nest:expectations=sha256:EXPECTATIONS_DIGEST`. Actual mount-table inspection
also rejects submounts, stacked roots, a different source and network filesystems.
Neither input metadata nor a directory in another dataset is sufficient. Seal
properties and ancestor safety are rechecked after the content scan.

Success prints exactly the existing root artifact object: `path`, `dataset_guid`
and `content_digest`. Append `--content-digest sha256:DIGEST` to require an earlier
aggregate identity rather than emit a changed one. Exit 1 is an admission failure;
diagnostics do not include native stderr, private paths/contents, xattr values or
per-file key hashes. Argument errors use ordinary argparse exit 2.

The aggregate SHA256 is domain-separated as `nest-stage3-root-v1`. It binds sorted
relative raw filename bytes, file types/modes, owner/group, nanosecond mtimes,
device identities, sorted xattr names/values (including supported ACL metadata),
symlink targets, hardlink topology and regular-file bytes. Variable fields use
eight-byte big-endian length framing; regular-file data uses the declared size.
Inodes, filesystem device IDs, ctimes and link counts are stability checks, not
portable digest fields. The scanner never follows symlinks, opens FIFO/device
contents, traverses another filesystem or accepts sockets. It checks file identity
and observed metadata before/after reads; unreadable metadata/content refuses.
Private root payloads must never be uploaded as public CI evidence. The aggregate
is a content identity, not a signature, producer attestation or live authorization.

This command does not create/copy/seal a dataset, write a receipt into the root,
change aliases, inspect the live identity source, build an OS or enable Stage 3
candidate CI. The versioned publication producer and adapter must still call it
after sealing and retain/reopen the result. Its build-input properties deliberately
differ from the later host-local transaction generation's
`org.nest:release=sha256:MANIFEST_DIGEST`; do not treat this publication path as an
already admitted host-local generation. No historical root is retrofitted here.

### Explicit local Stage 3 root publication

`files/build/publish-stage3-root.py` copies an already completed, offline local
build tree into a new versioned filesystem, then seals and independently admits
it. This is an executing storage operation, not a read-only plan. Invoke it only
on an explicitly approved publication host with a preprovisioned private local
ZFS parent mounted at `/nest/releases/RELEASE/hosts`, mode 0700. Select that
parent's actual GUID independently; the command never chooses a pool, provisions
ancestors, changes quotas/reservations or makes room by deleting rollback data.

```sh
python3 files/build/publish-stage3-root.py \
  /PRIVATE_OFFLINE_ROOT HOST RELEASE PARENT_DATASET_GUID sha256:EXPECTATIONS_DIGEST
```

SOURCE must itself be one mounted, read-only local ZFS filesystem with no child
datasets or submounts. It cannot be `/`, the release tree, a symlink alias, a
directory in another filesystem or an NFS/container bind-mount view. All source
and destination ancestors must be root-owned without untrusted writers. This
command does not stop a running build, assemble mounted container volumes or
turn an arbitrary live container root into an offline source. The future Stage 3
adapter must materialize a complete offline build filesystem first; missing
repository or other mounted content must not be silently omitted. Legacy
running-container rsync remains separate and is not accepted as that input.

An exclusive destination mkdir reserves `HOST` before dataset creation. Existing
paths, symlinks, completed or interrupted publications refuse; no automatic retry
removes a reservation. Only the exact new child dataset is created, with
`canmount=noauto`, `exec=off`, `setuid=off`, `devices=off` and the frozen build
release/expectations properties. Rsync copies the entire sealed source using
archive/ACL/hardlink/xattr/numeric-ID and single-filesystem semantics, without
delete or hidden exclusions. `--modify-window=-1` preserves nanosecond mtimes
even when new directories/symlinks already have the same whole-second time.
The source's full aggregate identity and native
mount/GUID/read-only state are checked before and after copy. After pool flush,
the new child is set read-only and the existing admission checker must verify
its exact GUID, properties, mount closure and content digest against the source.
Parent identity is rechecked across reservation and publication.

Success prints only the existing `path`, `dataset_guid`, `content_digest` root
artifact. The executing adapter must retain/reopen it through the normal member
result path; stdout alone is not durable publication evidence. Native command
failure, timeout, changed inputs, incomplete copy or failed readback emits a
static exit-1 diagnostic and no accepted artifact. Argument errors use exit 2.
Failure retains reserved paths and any partial dataset for diagnosis, possibly
writable under the private parent; it never destroys, retries, advances an alias
or changes an existing root. Even a sealed result after failed admission is not
an accepted publication. Native operations are bounded to one hour each; source
and target root/Puppet writers remain trusted, not adversarial.

This is a local publication primitive, not end-to-end Stage 3 candidate execution.
Build-to-publication transfer/materialization, adapter/CI integration, capacity
policy, host-local generation delivery and release promotion remain unfinished.
No real ZFS mutation is exercised by its fixtures: they use real disposable
filesystems and rsync with mocked ZFS properties/commands. No production root,
private identity or OS build is created during source validation. Rollback stops
invoking the opt-in command and preserves completed and incomplete generations
for explicit diagnosis/retention decisions; it does not rewrite a historical root.

### Stopped-container root materialization

`files/build/materialize-stage3-root.py` assembles a completed frozen build's
image layer and its separate repository volume into an offline filesystem for
the local publication command above. It executes copying and ZFS sealing; it is
not a read-only probe. Run as root only on the explicitly selected local build
host, using a preprovisioned, initially empty writable ZFS staging filesystem
outside `/nest/releases` and its independently selected GUID:

```sh
python3 files/build/materialize-stage3-root.py \
  CONTAINER /PRIVATE_STAGING_ROOT STAGING_GUID /PRIVATE_RECEIPT_DIRECTORY
```

The separate existing receipt directory must be mode 0700 with safe root-owned
ancestors, disjoint from staging, the container layer and repository volume.
An exclusive `materialize-GUID.started` reservation is fsynced before mounting
or copying. An earlier interrupted or completed attempt refuses even if staging
is empty. No retry removes a reservation, destroys a dataset or makes space.

Podman must report one exact stopped/exited container with no live PID, pause or
exec sessions. Its mounts must be the existing `/nest` and `/falcon` host shares,
exactly `CONTAINER-frozen-repos` at `/var/db/repos`, and optional read-only QEMU
helper binds. Unknown mounts, SSH-agent sockets, volume plugins/options, mismatched
mount sources and any other container referencing that volume refuse. The stopped
build must have ordinary real directory ancestors at `/var/db/repos`. Hidden
image-layer repositories may be nonempty: the frozen volume replaces that exact
subtree as it does during the build. The layer copy retains the mountpoint but
excludes its children, including dotfiles, before copying the complete volume.
Neither source is deleted or modified; stale hidden repositories are not shipped.

The command mounts the stopped layer locally without starting it. Root and volume
trees must have safe canonical ancestry, be disjoint and have no submounts,
including same-device binds. It copies the image layer except the exact hidden
repository children with the existing archive/ACL/hardlink/xattr/numeric-ID/
nanosecond semantics, then copies the complete repository volume, including its
directory metadata. A read-only virtual composition of those two original trees
is hashed with the unchanged `nest-stage3-root-v1` contract: the repository volume
occupies precisely `./var/db/repos`, with no arbitrary exclusions. The whole
assembled target must match that aggregate before and after sealing, and the
repository subtree must also match its own complete aggregate. The original
complete image layer (including hidden repositories) and volume are independently
rehashed to reject mutation. Cross-tree hardlinks that cannot survive separate
copies refuse rather than losing topology unnoticed. Ordinary sealed-root
admission still hashes just the actual filesystem, with no replacement option
on its CLI. Host shares, emulation binds and
Podman's runtime-generated mounts are not release payload; their external content
is never traversed. Both source aggregates, stopped-container identity, volume
identity/exclusivity and target filesystem identity are rechecked before sealing.
This is bounded observational consistency with trusted privileged build writers,
not a container-engine-wide lock or adversarial writer protection. The caller
must exclusively own the build and staging filesystem during execution.

Checked non-forced unmount precedes pool flush and `readonly=on`. Exact local
mount/GUID/read-only state is reopened around the assembled content digest.
`materialize-GUID.json` is exclusively written mode 0600, fsynced and reopened
before success. The small schema-1 `nest_stage3_materialized_root` record contains
container ID, staging path, dataset GUID and aggregate digest; no key bytes,
per-file key hashes or native diagnostics. This private staging receipt is not
the versioned publication artifact or release manifest. Retain it privately,
then explicitly invoke publication with that sealed staging path. Each command
is bounded to one hour; operational failures use a static exit-1 diagnostic and
no accepted stdout receipt. Argument errors use exit 2.

Failure retains staging and reservations, including a possibly sealed root when
later receipt retention fails. Best-effort non-forced mount release after failure
does not mean that the copy or cleanup succeeded. No container restart, automatic
retry, dataset removal, quota change, alias, live identity repair or host action
is performed. Rollback stops invoking these opt-in primitives and preserves all
generations for explicit diagnosis. Fixtures use real disposable tree copies
and rsync, but fake Podman/ZFS responses: no actual ZFS or OS build is exercised.
The opt-in plan composition below now invokes these local primitives. Candidate
adapter/CI integration, remote transfer, capacity policy and host-local transaction
generations remain unfinished; candidate CI execution is still disabled.

### Local frozen Stage 3 completion through Bolt

`nest::build::stage3` now accepts `root_publication`, an explicit hash with exactly
`release`, `expectations` (`sha256:` plus the frozen expectations digest), `staging`
(absolute path), `staging_guid` (decimal string), `receipts` (absolute private
directory) and `parent_guid` (decimal string). Both GUIDs are independently selected
native resources, not values inferred from a mutable path. This requires the
existing complete frozen `catalog_inputs`/repositories/identity selection,
`deploy=false`, and `hostroot=/nest/releases/RELEASE/hosts/HOST`. Missing or extra
fields refuse. Frozen catalogs now refuse `deploy=true` outright: the legacy
running-container rsync path cannot claim immutable publication. Ordinary builds
without frozen catalogs keep their existing behavior.

Before any container initialization, the plan runs the verified executor's
`files/build/finish-stage3-root.py` with `--check`. This is read-only placement
admission: root-owned canonical disjoint staging, receipts, identity and publication
parent; private receipt/publication directories; exact local writable ZFS GUIDs;
initially empty staging; and absent destination and attempt records. It neither
creates resources nor reserves them, and it does not promise that capacity will
remain sufficient during a later build. Frozen builds no longer forward an SSH
agent socket into their container. Repository access must use the existing approved
non-agent path; ordinary legacy socket forwarding is unchanged.

After checked container stop and another installed-executor check, the plan invokes
the helper without `--check`. It repeats placement admission, retains/fsyncs/reopens
`finish-STAGING_GUID.started` mode 0600, invokes the existing stopped-root
materializer, reopens its private receipt, verifies the sealed staging GUID and
digest, then invokes the existing local publisher. Publication must have the exact
assembled digest and pass another native root admission. Only after private
`finish-STAGING_GUID.json` retention/fsync/readback does the helper return the
ordinary `{"root":{"path":...,"dataset_guid":...,"content_digest":...}}` object.
The plan checks its complete shape and exact selected host path before returning.
Sibling helper imports run together from `/opt/nest` inside the accepted executor,
not from Bolt's isolated single-script upload directory.

The direct helper's positional arguments are `CONTAINER STAGING STAGING_GUID
RECEIPTS HOST RELEASE PARENT_GUID EXPECTATIONS_DIGEST IDENTITY_ROOT`, optionally
followed by `--check`. Its default mode executes storage writes, never an OS build,
container restart or host update. Failures emit a static exit-1 diagnostic without
native output. No completed or partial attempt is overwritten or automatically
retried. Keep all staging/publication resources and private receipts after failure;
absence of the final record means no accepted completion. Stop invoking this
opt-in path to roll back source behavior; do not delete reservations to replay.

This plan path requires build and publication on the same approved local storage
host with the complete stopped-build shape documented above. Hidden image
repositories are replaced in the assembled view by the exact frozen volume;
neither source is silently cleaned. The plan does not provision staging/parents,
select capacity policy, transfer roots between hosts, retain public CI member
results or enable Stage 3 candidate CI. The local adapter below retains the
sanitized member result separately. The
caller must exclusively own the build and placement; preflight is not a lock,
and rerunning the whole build plan is not a resume interface. Fixtures exercise
real Bolt plan control flow and private receipt retention with fake native
resources, alongside the real filesystem/rsync tests for both existing primitives.
No live ZFS, identity, OS build, aliases or reset/reboot are exercised here.

A consumer has exactly `project`, `decision`, `reason` and `members`. Decision is
`rebuild`, `reuse`, `defer` or `retire`; reason is bounded printable text. Rebuild
and reuse require the exact nonempty selected member IDs for that project and
thus actual output rows. Defer/retire require an empty selection and cannot be
counted as rebuilt. A reused result still needs exact source, executor, base and
compatibility identities; reusing an incompatible historic output fails rather
than relabeling it as current. If compatibility is unproven, choose defer and
keep it out of accepted required consumer scope.

All selected producer projects must be classified. The audited known tool floor
also requires explicit decisions for Bolt, PDK, Agent, Firefox, Camofox, llama.cpp,
whisper.cpp, Hadrian, Chromium, GHC, r10k and Buildah, using their lowercase exact
`nest/tools/...` project paths. This floor prevents silently dropping those known
consumers; it is not automatic discovery of future projects or legacy tag users.
The independently reviewed expectation producer must include those additional
consumers and any required release scope. A self-selected smaller matrix cannot
prove full fleet/consumer closure.

## Config CI input publication

An opt-in config pipeline with `RELEASE_INPUTS=true` and a GitLab file-type
variable `RELEASE_EXPECTATIONS_FILE` publishes an independently reviewed complete
expectations document. Select the exact config commit already named by both
`sources["nest/config"]` and `executor.source`. The executing job's checked-out
HEAD and tracked cleanliness must match that source. Pipeline/job IDs and the
config project identity are required; conflicting build/executor/candidate modes
refuse. No source, base, consumer decision or missing matrix row is selected for
the caller, and no branch tip is silently resolved into a pin.

The `Freeze release inputs` job runs
`python3 scripts/nest-release-inputs.py --expectations "$RELEASE_EXPECTATIONS_FILE"`.
It validates the existing complete schema, canonicalizes JSON, and exclusively
creates `release-inputs/expectations.json` and `release-inputs/receipt.json`.
Files and directory are fsynced and exact bytes reopened before job success.
An existing directory or symlink refuses without overwriting earlier output.
GitLab retains these two files only on success; a partially failed job is never
an accepted input producer. The receipt binds source/pipeline/job and the raw
SHA256 of the actual retained expectations bytes. Consumer variable
`RELEASE_INPUT_SHA256` uses that bare lowercase hex digest; the embedded
`expectations_digest` includes the `sha256:` prefix. Canonical publication makes
their hex payloads equal, unlike an arbitrary pretty-printed input file.

Every nonempty `RELEASE_INPUTS` value suppresses config executor builds and both
deployment jobs before their usual rules, even an invalid value or conflicting
`EXECUTOR_ONLY`/`BUILD`. The input script accepts only the exact value `true`.
Ordinary test jobs still run; neither real OS builds nor downstream triggers are
launched by this path. Without the flag, ordinary config CI behavior is unchanged.
This is a non-building input publication path, not release promotion authority.

Supply only sanitized expectations. Valid free-text reason/compatibility fields
are not secret scrubbers. The producer does not log the document or native Git
diagnostics, fetch repositories, validate registry resources, build an executor,
or prove that the selected executor exists. Download and independently verify
the exact successful input job artifact and executor architecture job before
using them; never use latest-success artifacts. Since the config SHA is shared,
a new producer source first needs its ordinary accepted executor publication;
do not pair an old executor with a new config source merely to skip that boundary.

Stage 0/1/2 candidate CI consumers are now published through their accepted
source-only merge pipelines. They acquire exact config input/executor artifacts
and retain individual results; live job-token access has not yet been exercised.
Stage 3 source pipelines are isolated from legacy host-root builds and refuse
unsupported candidate flags. Multi-project trigger/needs integration, assembly,
resource admission and Stage 3 candidate execution remain unfinished.
Rollback disables this opt-in invocation and retains prior artifacts;
it does not rewrite historical input receipts or alter any release alias.

### Source-managed Stage 3 trust selection

For expectations containing Stage 3 members, input publication now reads
`data/release/trust.json` directly from the exact config Git source object already
bound by `sources["nest/config"]` and the producer receipt. It does not accept a
caller-selected policy file, discover a CA in the private identity tree, trust an
untracked working-copy replacement or resolve a newer policy from main. The
document has exactly `schema` (integer 1), `kind`
(`nest_release_identity_trust`) and `hosts`, a map of exact host tokens to reviewed
bare lowercase SHA256 digests of public CA PEM bytes. Wildcards, malformed pins,
unknown fields, missing hosts and a member with a different CA pin refuse before
any artifact directory is reserved. A policy may retain other hosts not selected
for this release; it does not add those hosts to the release matrix.

The initial source-managed map is deliberately empty. No live CA is enrolled by
this implementation, and no CA is generated or automatically approved. Populate
the public host/pin mapping only through the normal reviewed configuration change
after independent trust selection, then freeze release expectations against that
accepted config source and its matching executor. Selecting a new policy source
invalidates the old executor/source pairing; do not retrofit an old input receipt.
This policy is the public build-identity allowlist, not authorization to change
live host trust, perform a migration, build an OS release or reboot a host.

A successful Stage 3 input publication additionally retains and reopens canonical
`release-inputs/trust.json` as an on-success CI artifact. The existing receipt and
expectations schemas are unchanged: the exact producer/config SHA binds the policy
source, while the expectations digest binds each selected host and CA pin. Consumers
must still acquire the exact successful config input job, not accept a submitted
policy artifact or self-authored receipt as approval. Normal reviewed source/CI
is the trusted boundary, not a signature, custody service or cryptographic proof
of owner approval. The manifest validator alone remains metadata-only and does
not establish that boundary. Non-Stage 3 input publication remains unchanged and
does not need or emit this policy artifact. An input file cannot bypass the
separate Stage 3 CI refusal: candidate execution is still disabled.

This closes public CA selection at the input-freeze boundary only. The executing
Stage 3 adapter must consume those exact admitted inputs and perform private
generation admission; versioned root publication, release-wide operational policy
and live compatibility acceptance remain unfinished. Rollback stops opt-in input
publication and retains earlier artifacts. It never substitutes a mutable policy
or a newly discovered CA into an already frozen release.

## Candidate schema 1

The candidate has exactly `schema` (integer 1), `kind`
(`nest_release_candidate`), `release`, `expectations_digest` and `outputs`.
`expectations_digest` is `sha256:` of canonical expectations bytes, not a digest
of the original file's whitespace. The canonical encoding is ASCII JSON with
sorted object keys, compact separators, escaped non-ASCII, finite numbers and one
trailing newline. Array order is significant. Duplicate JSON keys, nonfinite
numbers and files larger than 4 MiB refuse. The imported `canonical(value)` and
`digest(value)` helpers implement this encoding for CI producers.

Each output has exactly:

- `member`: the complete corresponding expectations row, byte-value equivalent
  after JSON parsing. A changed CPU, mode, variant, base, firmware or ABI refuses.
- `producer`: exactly `project`, `sha`, `pipeline`, `job`. Project/source must
  match the frozen selection; pipeline/job are positive integers, not placeholder
  zeros or booleans. CI integration must independently read those resources.
- `executor`: exactly the expected executor object. A stale expected source or
  mismatched actual executor refuses.
- `artifacts`: Stage 0/1 require distinct `normal`/`debug` repository digest refs;
  Stage 2/tools require an `image` digest ref. Stage 3 requires a `root` object
  with exactly `path`, decimal-string `dataset_guid` and `content_digest`
  (`sha256:` plus 64 lowercase hex digits). Root path must be the exact versioned
  host destination above; duplicate dataset identities refuse.

Missing, duplicate, unexpected or partially published member rows cannot produce
a retained release manifest. Normal/debug outputs remain per CPU/variant pair;
aggregate OCI indexes never substitute for missing matrix members. Unknown
fields at every schema object boundary refuse rather than being silently copied.
The retained schema-1 `nest_release_manifest` embeds both exact `expectations`
and `candidate`, so it remains interpretable after the input files disappear.

## Trust, publication and rollback boundaries

Config executor CI now pins its Git checkout to `CI_COMMIT_SHA`, verifies that
exact HEAD after cloning even if the branch moves, and sets the OCI revision
label. The local branch name is retained at that exact commit because `bin/build`
derives Stage 3's default Puppet environment from it. Each architecture publishes
a unique pipeline/job/CPU tag through the existing remote digest-readback helper.
`bin/ci-executor-receipt record REF_FILE
JSON_FILE` opens that digest with no container network, host mounts or writable
root, checks its Git HEAD and revision label, then exclusively writes and
reopens one schema-2 `nest_config_executor_member` receipt. The input reference
must belong to the current CI registry repository/ref slug. Failed inspection,
wrong source, malformed input or an existing receipt refuses without replacement.
No submitted command output or environment is copied into the artifact.

The build job retains `executor-receipts/` as normal GitLab artifacts. The image
deployment job downloads those successful prior-stage artifacts and invokes
`bin/ci-executor-receipt refs executor-receipts`: exactly the expected Haswell,
Cortex-A53 and SiFive-U74 receipts must match this project, source and pipeline,
with distinct positive job IDs and digest references. Only after the complete
set validates are refs emitted for OCI index assembly. It never substitutes a
mutable CPU tag for a missing member. A single-CPU `BUILD` run still does not
publish an aggregate. These executor receipts are not Stage 0/1 output pairs or
a completed release manifest; they do not attest module or base-image
compatibility or GitLab job status independently. CI artifact origin and normal
job dependency success remain part of the trusted pipeline boundary.

Schema 2 also embeds `inputs`, a schema-1 `nest_config_executor_inputs` record.
CI pulls the selected Bolt base once and passes a repository-qualified digest
from Podman's image readback to `BOLT_IMAGE`; the Containerfile consumes that
exact reference. Direct Containerfile callers must likewise pass an exact base.
After normal module installation, the nested `.modules/nest` checkout fetches
the already cloned exact config commit locally and detaches there, rather than
trusting the control branch still points to that source.

Executor receipt verification pulls the exact published digest under a bounded
600-second transfer/unpack budget, then checks inputs and Git source in offline,
read-only containers with separate 180-second command limits. The OCI label is
checked independently. Static phase/timeout diagnostics never echo native
registry errors or credentials. A timeout still refuses the receipt and aggregate;
the larger transfer budget is not acceptance of an incomplete check.
Both offline checks disable Podman's automatic read-only tmpfs mounts with
`--read-only-tmpfs=false`. Neither needs writable temporary storage. This avoids
copying image-resident temporary build trees into tmpfs before the verifier starts,
while retaining the image's read-only paths and the existing verification limits.

`scripts/nest-executor-inputs.py record --source SHA --base DIGEST_REF` records
the exact top-level and nested Nest source, Puppetfile digest, and every installed
module's name, optional Git HEAD and content digest. It requires the existing
Nest, private, stdlib, reboot, Ruby task helper and KubeCM modules. Git-backed
modules may have Bolt's installer-pruned tracked deletions, but modified, added
or type-changed tracked files refuse. The nested Nest module is force-checked out
inside this build-owned image to restore the complete exact source before hashing;
the top-level and nested Nest source must be clean. This never resets an operator
checkout or a live host. The file digest covers relative paths,
file bytes, permission bits, directories and symbolic-link text; Git internals
are excluded and links are never followed. Link identities do not prove their
referents are available or compatible. The entire installed module set, including
ignored/untracked module content, participates. Missing/added/changed modules,
bytes, paths or permissions fail the subsequent exact readback. No file contents,
remote URLs, credentials or full environment enter the public receipt.

The build workspace retains `.executor-inputs.json` in the image via exclusive
creation and fsync. `check` recomputes all identities read-only and requires exact
bytes. The receipt producer runs that check in the actual published digest image,
with no network, host mounts or writable root, before retaining the embedded
sanitized identities. Failure emits no accepted receipt. The aggregate reader
requires schema 2; earlier schema-1 artifacts remain historical source/pipeline
evidence, not module-complete receipts. Do not silently upgrade them with the
current module set or rebuild old outputs merely to produce new metadata.
This records consumed modules; it does not freeze their mutable upstream refs
before installation, prove compatibility, or reproduce historical modules on
rebuild. Release producers must select the exact accepted executor digest and
compare its retained input inventory, not reinstall modules from main.

Legacy CPU tags and both `latest` executor aliases remain compatibility outputs,
not immutable release inputs. Concurrent older pipelines can still replace
those aliases out of order; use the retained digest identities, not tag recency,
for release selection. This slice does not implement release alias admission or
compare-and-swap. Rollback restores the previous CI source only for subsequent
tooling builds; preserve all already published digests and do not use a failed
receipt as a reason to launch OS builds or host actions.

These are sanitized metadata documents. Never supply private keys, tokens, full
environments, certificates or backup contents. The tool rejects unknown fields
but does not scrub secrets placed inside valid free-text reason/compatibility
fields or path values. Review/sanitize the producer payload before artifact
publication; manifests are mode 0644 and intended for normal CI artifact use.

Metadata validation cannot establish that a referenced image exists, that its
actual contents match firmware/ABI assertions, that a producer job succeeded,
or that a ZFS root is immutable/readable. Required resource readbacks, executor
labels/source verification and compatibility checks must precede acceptance or
alias replacement in the later real CI consumer. No signatures are invented.
A manifest digest is content identity, not signer identity or approval.

Do not infer a live deployment from a valid candidate or publish a new release
alias merely to exercise this validator. Existing build defaults and mutable
aliases are unchanged. Rollback stops invoking this opt-in validator and retains
previous manifest/artifact digests; it does not rebuild an old release from main,
destroy a generation, alter a host, or relax a failed admission gate.

## Frozen browser candidate producers

The existing `nest::build::firefox` and `nest::build::camofox` wrappers now accept
`candidate`, `from_image` and complete `repo_revisions`, using the same executing
adapter interface below. Frozen Firefox selects `zen5` with variant `workstation`;
its legacy fresh base CPU remains `haswell` because Stage 1 has no zen5 workstation
output. Camofox selects `zen5` with variant `server`. These are distinct base and
runtime contracts, not interchangeable browser images. The release owner must
verify the selected digest's actual CPU/variant compatibility before execution;
the wrapper's syntax checks alone cannot establish it.

Candidate mode requires build, init and deploy, an exact base, all three source
pins, no tag override and a remote registry. Existing runner registry authentication
is required; credential parameters refuse. Fresh/refresh remains the frozen
member's ordinary recipe. The adapter dispatches each specialized wrapper, not
the generic plan directly: Firefox's headless smoke and Camofox's tab-creation
smoke must pass, followed by another frozen-repository check and checked stop.
Only then is `candidate-TOKEN` committed and remotely verified. Firefox retains
CMD `/usr/local/bin/nest-firefox-browser` and WORKDIR `/home/kasm-user`; Camofox
retains CMD `/usr/local/bin/nest-camofox-browser` and WORKDIR `/home/node`.
Failure emits no accepted result, although a failed push can leave an unselected
candidate. Existing latest/custom-tag publication is unchanged outside candidate
mode. The returned value is exactly one same-project repository digest `image`.

These source interfaces do not yet enable either repository's frozen CI consumer,
prove actual browser UX, build or publish an image, promote aliases or change the
live services. PDK remains unsupported by the frozen adapter until its specialized
smoke and private gem configuration contract is implemented. The native DAG,
resource admission and separately authorized release exercise remain required.
Rollback stops supplying candidate options; preserve existing digests and failed
attempts rather than replaying a build or moving production aliases.

## Frozen Stage candidate producer

`python3 /opt/nest/bin/ci-release-build --expectations FILE --member ID
--executor-receipt FILE --output-dir ABSOLUTE_DIRECTORY` is an executing build
entrypoint, not a read-only planning command. Invoke it only in an approved
Stage CI job using a pinned config executor image. It runs exactly one existing
`nest::build::stage0`, `stage1`, `stage2` or `stage3` candidate plan through the existing
cleanup wrapper, passing JSON parameters over stdin. It never calls a host
update plan or changes ordinary CPU/platform/latest aliases. Candidate image
publication is a real side effect and requires the build scope's authorization.

The full frozen expectations file selects one `rebuild` member. Stage 0 currently
supports only refresh of a Nest base with the server profile; raw Gentoo/fresh
bootstrap is intentionally rejected. Stage 1/2 preserve explicit fresh/refresh,
normal/debug base distinctions, CPU/platform/variant and all three repository
pins. The direct llama.cpp and specialized OpenBolt/Agent paths are supported below; other
tools refuse instead of bypassing their specialized wrappers, except for the specialized
browser paths documented below. Stage 3 supports only explicit fresh initialization and requires the
additional local placement contract below; refresh refuses. Candidate/container names derive from positive CI pipeline/job
IDs, so one member must run per CI job. No arbitrary plan parameter overrides
are accepted; existing Hiera resource policy remains in effect.

Before execution, the adapter checks the Stage project's actual Git HEAD and
tracked cleanliness against `CI_PROJECT_PATH`, `CI_COMMIT_SHA` and the frozen
source selection. `CI_JOB_IMAGE` must equal the selected exact executor digest.
The selected schema-2 config member receipt is validated in its original config
pipeline context; the installed executor's source, Puppetfile and complete
module inventory are independently recomputed and must equal that receipt and
the image's retained input record. These checks repeat after execution. CI image
selection and artifact origin remain trusted GitLab/runner boundaries, not a
signature or independently queried proof that an untrusted runner used that
image. Do not accept an arbitrary user-supplied receipt as a trusted CI artifact.

The adapter derives candidate-only publication and complete frozen repository
arguments from the selection. It relies on existing registry authentication;
credentials are not command parameters or result fields. Bolt's actual JSON
return must contain the complete expected digest pair/image in the producer's
exact registry/project/variant repositories. Partial, mutable, wrong-repository
or identical normal/debug content refuses. The existing candidate plans perform
remote digest readback. No success can be produced merely by submitting output
metadata or by relabeling an old build.

The caller must provide an existing canonical absolute artifact directory. An
exclusive `.ID.started` reservation is written before any build. A failed,
interrupted or previously completed attempt cannot execute again in that same
directory. Use a fresh CI job and private workspace after diagnosis, not deletion
of the reservation to blindly replay a build. On success, exclusive `ID.json`
creation, file/directory fsync and exact readback retain a schema-1
`nest_release_member_result` with release/expectations digest, original executor
receipt and the complete `output` row for later candidate assembly. Stdout is a
small member/digest/readback receipt. Raw Bolt stdout/stderr is private temporary
data and is not published; failure emits a static sanitized diagnostic. This is
not a resumable OS build engine; GitLab job cancellation and the existing wrapper
own cleanup, while partial candidate digests remain unselected.

Stage 0/1/2 project CI implements exact expectation/executor artifact acquisition,
image selection, this entrypoint and retained `ID.json`. Live job-token permissions
and downstream successful-job binding remain unverified. Candidate assembly,
Stage 2 firmware/ABI resource verification, native multi-project DAG, release
promotion/rollback and Stage 3 CI acquisition/retention and host-local transfer remain
unfinished. A successful adapter fixture or metadata compatibility string is not
hardware boot or whole-release compatibility proof. Rollback stops invoking the
opt-in adapter; preserve published candidates and receipts rather than rebuilding
historic outputs or changing live aliases.

### Stage 3 adapter local placement

The current explicit provisioning and promotion interfaces are documented in
[release publication](nest-release-publication.md). They extend this placement
schema; historical delivery limitations below are not a current implementation
checklist. No source interface grants build or promotion authority.

For one approved Stage 3 build, append `--stage3-placement FILE`. This file has
exactly `schema` (integer 1), `kind` (`nest_stage3_local_placement`), `member`
(the selected member ID), `expectations_digest` (the exact prefixed digest of
the full expectations), `staging`, `staging_guid`, `receipts` and `parent_guid`.
Paths are canonical absolute strings; GUIDs are positive decimal strings.
The latter four fields select the already provisioned local resources documented
above. The adapter neither selects a pool nor creates staging or its parents.
Missing/mismatched/extra fields refuse before Bolt. Supplying placement for
another stage also refuses; it is not a generic plan-parameter escape hatch.

Run on the same explicitly approved local build/publication host, with the native
root/ZFS/Podman permissions and mount view required by the plan and checkers.
An ordinary CI container with only an NFS `/nest` view is not sufficient. No remote
placement, privileged-runner selection, capacity policy or automatic storage
provisioning is implied by this interface. The file is a trusted caller's placement
choice bound to frozen expectations, not authorization to build a release.

The adapter passes the exact Stage 2 base, repository pins, private identity
generation/CA pin and accepted executor catalog inventory to `nest::build::stage3`.
It supplies `root_publication` and the exact versioned hostroot with `deploy=false`;
no candidate registry flags, legacy rsync or served Puppet environment are used.
The existing plan admits placement before initialization, completes the checked
build and stopped-root publication, and retains its private completion receipt.
After the plan returns, the adapter rejects malformed/wrong-path root objects
and independently invokes `check-stage3-root.py` with the returned exact GUID,
expectations digest and content digest. Only identical native readback followed
by the installed-executor recheck permits ordinary `ID.json` retention/readback.
Native check failure, changed content or interrupted result retention leaves the
attempt reserved and no accepted member; it never retries or deletes resources.
Private identity/root payloads and native diagnostics are not public CI artifacts.

The adapter fixtures use real disposable Git/module inventories and fake Bolt and
native root admission. They do not exercise live ZFS, identity or OS builds. Stage 3
project CI still refuses candidate execution until its separate exact artifact,
placement, executor and retention integration is delivered. Host-local generation
transfer, operational capacity policy and disruptive canary acceptance remain open.

### Generic tool candidate inputs and llama.cpp adapter

`nest::build::tool` now accepts optional `from_image`, `repo_revisions` and
`candidate`, with the same exact digest, complete three-repository and token
contracts as the Stage plans. A base pin requires initialization; frozen inputs
additionally require a build and reject all extra volume overrides, which could
otherwise hide the admitted repository tree. Frozen mode recreates only the
named `CONTAINER-frozen-repos` volume at `/var/db/repos:nocopy`, prepares exact
detached commits, skips `eix-sync`, and checks complete inputs after the tool
catalog before stopping/committing. It never removes the ordinary repository
cache. Missing pins, drift or preparation failure stops publication.

Candidate mode requires build, init, deploy, an exact base, a remote registry
and no explicit `tag`. It commits/pushes only `candidate-TOKEN` in the existing
tool repository, then uses the shared native remote digest reader. Only an
exact same-repository digest permits the returned `{image: REFERENCE}` result.
Push/readback failure leaves an unselected partial candidate, never an alias
update or accepted result. Candidate mode alone does not freeze repositories;
supply the complete pins as well. Direct callers still own executor selection.
Ordinary cached builds, fresh/refresh base defaults and tag/CPU publication
are unchanged without these options.

The existing `ci-release-build` adapter supports the direct `stage=tool`,
`project=nest/tools/llama.cpp`, `variant=server` path. It preserves explicit
fresh/refresh and uses the existing generic plan with exact base and repository
pins. Source checkout, pinned executor/module identities and post-build checks
are identical to Stage producers. Tool results have one exact image in the
project repository, with no variant suffix; the adapter exclusively retains
and reopens the ordinary member result. Its reservations still prevent replay
after failure or success. This adds no new schema or arbitrary plan override.

PDK, Firefox and Camofox still refuse in this adapter: their
existing wrapper smoke tests and image changes must be preserved during their
separate integration. Do not call the generic path to bypass them. Other known
consumers still need explicit reuse/defer/retire decisions. The llama.cpp
repository's exact artifact acquisition and candidate CI are source-delivered in
MR !2, merge `8674d7f0cb9af46851a2d8208867e7ca0f16c396`; no actual candidate
build or publication is proven. Bootstrap/DAG edges, compatibility admission and
alias promotion remain unfinished. Source tests use
the actual Bolt plan with its mock executor and the real adapter with disposable
Git/module fixtures and fake Bolt; they launch no real tool/OS builds or registry
writes. Rollback stops passing the new options and retains old exact digests;
never relabel a mutable rebuild as the same release.

### Specialized OpenBolt candidates

`nest::build::bolt` accepts optional `from_image`, `repo_revisions` and `candidate`.
Candidate mode requires a fresh execution (`build=true`, `init=true`,
`deploy=true`, complete exact repository pins and a digest base), no tag override,
a remote registry and one actual supported CPU: haswell, cortex-a53 or sifive-u74.
Both frozen fresh and refresh modes are supported. This does not invoke the
generic publisher directly or weaken its build/init guard for a publish-only call.

The existing generic tool plan builds without publication, using the exact base
and isolated repository pins. The wrapper then starts the completed container,
runs the existing `bolt`, `bolt --version` and multi-object Podman JSON parser
smoke, rechecks frozen repositories, and performs a checked stop. Only afterward
does it commit `candidate-TOKEN` with the existing `CMD=/bin/zsh`,
`BOLT_DISABLE_ANALYTICS=true` and `BOLT_GEM=true` image changes. The same shared
native publisher must return one exact `nest/tools/bolt@sha256:DIGEST`. Any smoke,
repository, stop, commit, push or digest-readback failure stops the result. A
partially pushed candidate may remain unselected for diagnosis; no CPU tag,
aggregate alias or config pipeline is advanced.

Candidate mode deliberately does not inherit Hiera registry credentials, and
explicit username/password parameters refuse. It uses the already authenticated
runner/Podman registry contract, like the frozen Stage adapters. Real registry
authentication and a built OpenBolt executable are not proven by fixtures.
Without candidate mode, existing credential defaults, smoke and legacy CPU-tag
publication are unchanged.

`ci-release-build` routes `stage=tool`, `project=nest/tools/bolt`, `variant=server`
to this specialized wrapper, never to `nest::build::tool` as a direct producer.
It validates the same source/executor/module identities before/after execution
and retains/reopens the ordinary one-image member result. A changed/unsupported
CPU or variant refuses before Bolt. The OpenBolt repository consumer and exact
artifact acquisition are source-delivered in MR !2, merge
`c99438ae93727612d702a94abd2170fc20017b7e`. The native bootstrap/DAG edge remains separate source work;
no real OpenBolt/OS build, alias promotion or host action was exercised here.
Actual-plan mocks cover smoke/publication refusal and legacy compatibility;
disposable Git/module fixtures plus fake Bolt cover all CPU/mode dispatches.

### Specialized Agent runtime candidates

`nest::build::agent` accepts optional `from_image`, `repo_revisions` and
`candidate`. Candidate mode requires build/init/deploy, a digest base, complete
isolated repository pins, no tag override, a remote registry and the actual
supported CPU `zen5`. Both frozen fresh and refresh modes are supported.
It builds through the existing generic tool plan without publishing, then runs
the existing terminal-shell, `glab --version` and `git --version` smoke commands.
Frozen repositories are checked again after smoke, followed by a checked stop.
Only then is `candidate-TOKEN` committed with the existing `CMD=/bin/zsh` and
published through the shared native publisher. Its returned image must be the
exact `nest/tools/agent@sha256:DIGEST`; no `latest` or CPU alias is advanced.

Candidate registry username/password parameters refuse, and candidate defaults
do not inherit Hiera credentials. Existing runner/Podman authentication remains
required and is not proven by fixtures. With candidate mode absent, legacy
`latest` defaults, explicit tags, smoke and ordinary publication are unchanged.
The adapter binds `stage=tool`, `project=nest/tools/agent`, `variant=server`,
`cpu=zen5` to this specialized wrapper. It checks the same actual source,
executor/module identities before and after execution and retains/reopens the
ordinary one-image member result, with exclusive reservations preventing replay.
Unsupported CPU/variant, failed smoke, repository drift, failed stop/commit/push
or wrong digest cannot produce accepted completion. Partially built/published
resources remain unselected for diagnosis; no automatic deletion or replay occurs.

Actual-plan tests exercise all smoke failures, post-smoke drift, stop/commit/push
failures, digest rejection and legacy defaults/explicit tags. Disposable Git/module
fixtures and fake Bolt exercise both modes and failed retained outputs. No real
Agent/tool/OS build, registry authentication/publication, host change or Hermes
runtime change is exercised. The distinct Agent repository CI consumer and native
bootstrap/DAG integration remain unfinished. Stop passing candidate options to
roll back source behavior; preserve exact prior digests and receipts.

## Isolated verification

### Opt-in frozen Stage 3 catalog

`nest::build::stage3` accepts optional `catalog_inputs`, with exactly `source`
(the full lowercase config Git SHA) and `base` (the config executor's exact Bolt
base image digest). These identify the existing retained executor input inventory,
not the Stage 2 image. Use the accepted digest-pinned config executor and its
`/opt/nest` Bolt project; do not point Bolt at a different project or modulepath.
The trusted CI invocation must select that executor and validate its retained
schema-2 receipt. This plan option alone is not an attestation of CI image use.

Frozen catalog mode requires `build=true`, `init=true`, complete `repo_revisions`,
an exact `stage2_image` and no `puppet_environment` (even an explicit empty string
refuses). The existing installed input checker verifies both config checkouts,
Puppetfile, base and every module's paths/content/permissions before container
initialization and before/after final configuration. A failed check stops the
plan. The final catalog uses Bolt `apply { include nest }`, compiled locally from
the verified executor module set, with the existing Stage 3 target facts. It does
not run `puppet agent` or fetch a mutable served catalog. Existing local identity
and profile applies retain the same executor context. Ordinary invocations without
`catalog_inputs` retain the served environment and Puppet detailed-exit behavior.

Frozen mode also requires a separately provisioned private `identityroot`; its
legacy default equal to `hostroot` now refuses before container removal, repository
creation or package work. `files/build/check-stage3-paths.py IDENTITY OUTPUT HOST`
now requires a fourth argument, `CA_SHA256`, the independently approved bare
lowercase SHA256 of the public CA PEM file bytes. `nest::build::stage3` takes it
as `identity_ca_sha256`, mandatory with `catalog_inputs`; missing, malformed or
changed pins refuse before mutation. This deliberately tightens the opt-in frozen
interface; ordinary builds without `catalog_inputs` remain unchanged. Obtain the
pin from the release's reviewed trust policy, not by automatically accepting the
current identity tree's CA. A pin selected from that same unreviewed input would
only prove self-consistency, not approved trust. This is public CA content identity,
never a key fingerprint. The checker is read-only admission, invoked locally before initialization
and before/after final configuration. Both paths must be canonical absolute paths
without symlink aliases or equal/ancestor/descendant overlap. The identity's entire
ancestry and existing output ancestors must be root-owned directories without
untrusted writers. Existing machine-id must be a nonzero lowercase 32-hex value.
The existing SSL tree must contain `certs/ca.pem`, `certs/HOST.pem` and
`private_keys/HOST.pem`. Copied SSL material permits only root/Puppet ownership,
no untrusted writers, regular readable nonempty files, protected directories and
private keys without group/other access. Links and special files refuse, including
extra files in the recursively copied source. The checker emits no identity
values, certificates, keys or key digests. Exit 1 is sanitized failure; argument
errors use argparse exit 2.

The checker reads bounded material into private process memory, compares the
certificate and private key's public keys, and requires exactly the selected host
as its single common name. Wildcards, a matching SAN with a different common name,
multiple leaf PEM objects, encrypted keys and trailing unrelated material refuse.
Native OpenSSL validates current validity, the client-auth purpose, host name and
chain against only the pinned CA bytes. Default file/directory/store trust and
inherited OpenSSL configuration are disabled. Each command is bounded to 15 seconds
and native diagnostics are discarded. Linux sealed anonymous memory supplies the
exact approved CA to OpenSSL without creating a temporary file; unsupported
OpenSSL options or missing tools fail closed. The executor requires OpenSSL 3,
Linux `/proc/self/fd` and Python's memfd/sealing support. No CA, key or cert is
generated, repaired or renewed by admission. This is not a revocation-status or
remote TLS endpoint check; no CRL/OCSP fetch or network command is performed.

After container initialization and apply preparation, frozen identity setup invokes
the same checker with `--install` inside the disposable build container. This
explicit executing mode requires root and Podman's `/run/.containerenv`; the
default invocation remains read-only. It captures machine-id and the complete SSL
tree into bounded private process memory (at most 4096 entries and 16 MiB total,
with the existing 1 MiB per-file limit). A complete metadata inventory before and
after reading detects changes to device/inode, size, ownership, permissions,
mtime/ctime or membership, including empty directories. Source admission repeats,
and the actual captured certificate/key/CA bytes undergo the same cryptographic
checks. Concurrent source changes fail the build; there is no automatic retry.

Only those captured bytes are staged under a unique mode-0700 directory on the
container's destination filesystem, with private file creation and admitted final
ownership/modes. SSL replacement removes stale files from the previous build
identity; machine-id and SSL bytes are reopened and compared before success.
Staging is removed on both success and failure. No working copy goes onto shared
`/nest` or final backup storage. Frozen Puppet identity setup no longer reopens
the live source. A partial install aborts this disposable build before profile or
package work; it is not a live-host atomic migration or a resumable repair. It
must not be invoked in a live service container. Source mutation after capture
cannot change the bytes being installed; root/Puppet writers and the executor
remain trusted, and this is not protection against a malicious privileged writer.

This does not generate machine identity, repair or alter the private input tree,
or renew credentials. Legacy initialization remains available without
`catalog_inputs`. Missing identities use their separately approved provisioning
workflow. CA selection must still come from reviewed release trust policy, not
auto-trust of the same input. The private generation interface below now binds
subsequent frozen builds to one retained capture. Release manifest integration
and reviewed trust-policy selection remain required before the Stage 3 adapter.
No key hashes or secret bytes enter public receipts or diagnostics.

### Private identity generation reference

Frozen `catalog_inputs` now also requires `identity_reference`, a canonical
lowercase UUID v4 selected for this capture. `identityroot` must be the exact
completed generation directory with that UUID as its basename, not the mutable
legacy host identity source. The same reference is checked before initialization,
during captured-byte installation and around final configuration. Missing,
partial, changed or mismatched generations halt before the next build phase.
Ordinary legacy builds without `catalog_inputs` remain unchanged.

Explicit capture is a separate root-only operation, not automatic repair by a
build. Provision a root-owned mode-0700 parent on private local durable storage,
outside the source and versioned host-root publication trees. Then invoke:

```text
python3 files/build/check-stage3-paths.py SOURCE /PRIVATE_PARENT/UUID HOST CA_SHA256 --publish-reference UUID
```

SOURCE is an existing admitted identity tree. UUID is the caller-selected v4
reference; CA_SHA256 is independently approved public CA PEM identity, not an
automatically accepted digest of SOURCE. The checker creates no keys, certs,
machine IDs, snapshots, aliases or network requests. It first takes the existing
stable bounded memory capture. An exclusive mkdir reserves the new generation;
an existing directory (even empty or incomplete) or concurrent writer refuses,
never overwrites or silently retries. Files are privately staged, fsynced, copied
and reopened. Directories are fsynced before the completion marker, then the
generation and its parent are fsynced and the whole completed capture read back.
The source and all prior generations remain untouched. Failures after reservation
can leave an incomplete private directory; retain/inspect it and select a new UUID
instead of deleting the reservation to replay blindly.

The root is mode 0700 and `.nest-identity.json` is root-only mode 0400. This PRIVATE
record binds the reference, host, public CA pin, exact copied path set, modes,
owners and file digests, including private-key digests. Never copy the record or
any generation file into public CI artifacts, logs or release reports. Only the
opaque UUID, reviewed public CA pin and private generation path may enter the
later sanitized release interface. No record bytes or key hashes are printed.

Read-only verification uses the original positional arguments with the completed
generation as IDENTITY and adds `--identity-reference UUID`. `--install` may be
added only inside the disposable build container. The private marker is read
before and after the stable capture and compared to the exact canonical record
recomputed from captured bytes and metadata. Added/removed paths, changed machine
ID, valid-but-replaced identity, modes, reference or trust binding all refuse.
Private marker and source bytes are never installed into the image as receipts;
only the admitted machine ID and SSL material are installed. `--publish-reference`
and `--install` are mutually exclusive. All operational failures use the existing
static sanitized exit-1 diagnostic; argument errors retain argparse exit 2.

This is write-once by the supported interface and content-bound on every read,
not ZFS filesystem immutability, signing, custody, or protection from privileged
writers who can replace both private content and its record. Root/Puppet and the
private storage boundary remain trusted. No real private generation is created
as part of source validation; tests use disposable synthetic TLS identities.
The release schema binds the opaque reference and public CA pin, but the Stage 3
candidate adapter and reviewed release-policy selection remain unfinished.
Stage 3 CI still refuses candidate execution.

This is an executing build option, not a read-only command. It does not publish a
versioned host root, make dynamic external data
reproducible or validate hardware compatibility. Existing rsync publication remains
legacy behavior: callers must not treat that path as an immutable generation or
use it for release-candidate success. Stage 3 CI still refuses candidate execution.
Versioned publication, identity ownership/admission and the executing Stage 3
candidate adapter must land before that boundary can be enabled. No host update,
reset, reboot, release promotion or cleanup is triggered by this option.

Rollback stops passing `catalog_inputs` and preserves accepted images/receipts;
it does not replay a partially executed build or substitute a mutable catalog into
an already accepted frozen release.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 spec/files/nest_release_manifest_test.py
PYTHONDONTWRITEBYTECODE=1 python3 spec/files/ci_release_build_test.py
PYTHONDONTWRITEBYTECODE=1 python3 spec/files/build_stage3_paths_test.py
PYTHONDONTWRITEBYTECODE=1 python3 spec/files/build_stage3_trust_test.py
PYTHONDONTWRITEBYTECODE=1 python3 spec/files/build_stage3_capture_test.py
PYTHONDONTWRITEBYTECODE=1 python3 spec/files/build_stage3_reference_test.py
```

The suite uses conspicuously fixture-only sources, identities and image refs.
It executes the real CLI read-only and retention paths, tests concurrent
publishers, removes inputs before reopening the retained file, and injects
missing debug/member rows, moved pins, stale executors, wrong firmware/CPU/mode,
identity overlap, unclassified tools, failed publication and malformed JSON.
It performs no network access, Podman build, ZFS operation or live host action.
The existing all-branch CI fixture job runs this suite.
