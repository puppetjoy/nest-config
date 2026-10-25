# Native compiler snapshot hooks

`files/puppet-versioned-code.rb` implements the paired native Puppetserver
code-ID and static-content command contracts. It is a source component, not a
new deployment service. The OpenVox chart has an opt-in pod-private integration;
no production or test service selects it by default.
The existing consumer-side optional `code_id` field does not establish compiler
provenance without the publication and lifetime guarantees below.

## Supported interface

Run both commands through small fixed-path executable wrappers. Puppetserver
adds its native arguments after the wrapper's fixed arguments:

- `ruby puppet-versioned-code.rb id ROOT RECEIPT ENVIRONMENT`
- `ruby puppet-versioned-code.rb content ROOT RECEIPT ENVIRONMENT CODE_ID FILE_PATH`

`ROOT` is the frozen `main` environment directory, not its parent. `RECEIPT` is
an independently expected release JSON object with exactly these fields:

- `schema`: integer `1`.
- `environment`: string `main`.
- `source`: full lowercase Git SHA for the accepted control-repository source.
- `code_id`: `sha256:` followed by the lowercase SHA256 of the tree inventory.

The Ruby library exposes `inventory(ROOT)` and `code_id(rows)` for the release
producer. The inventory is a sorted array of relative-path records: directory
and file permission modes, SHA256 file content, and contained symbolic-link
targets. Git administration entries named `.git` are excluded. Special files,
escaping symlinks, missing intermediate link targets, control-character paths
and empty trees fail.
Inventory JSON uses ASCII escaping and one trailing newline before hashing.
A contained symlink to a missing final leaf is retained in the inventory (the
existing firmware alias is one example), but cannot serve static content.
Missing intermediate directories and links escaping the snapshot still refuse.
No file contents or secret values belong in the public receipt.

The frozen `environment.conf` must contain only the following assignments
(comments, blank lines and ordering do not matter):

    modulepath = modules:.modules
    manifest = manifests
    config_version = /bin/echo FULL_SOURCE_SHA

The helper refuses writable mounts, mismatched source/configuration, mismatched
expected tree identities, other environments, and static paths outside a
module's `files`, `lib`, `scripts`, or `tasks` directory. It streams bytes only
after validation. Unknown or invalid requests exit nonzero with a sanitized
error. It never generates a new expected identity to excuse drift.

## Publication and compiler-lifetime requirements

### Expected identity from immutable executor inputs

The existing executor `Containerfile` now runs this producer after recording
and checking its complete installed module inputs:

    python3 scripts/nest-compiler-release.py --project /opt/nest \
      --destination /opt/nest-compiler-release --source FULL_SOURCE_SHA \
      --base BOLT_IMAGE_AT_DIGEST

This is a build-only projection in the existing executor image, not a live
r10k observation or a new publication service. It checks the control Git source
and unchanged tracked files, the exact base, Puppetfile digest and all installed
module identities against `.executor-inputs.json` before copying and again
afterward. Run it only with immutable input bytes and no concurrent writer;
the double check is not a substitute for that isolation.

The private output contains `main`, `expected.json` and `executor-inputs.json`.
The environment includes the tracked control Hiera data and configuration, the
real `site.pp` relocated to `manifests/site.pp`, and every installed module.
Untracked/ignored control data and Git administration are not compiler inputs.
It preserves the existing served-Nest `spec` pruning boundary and relocates the
known `.modules/nest/data/private` link to `../../private/data`, the accepted
sibling private module, instead of a nonexistent nested Bolt installation.
The root `data/private` link already targets that same private module. No
other input pruning or link rewriting is performed. File modes and relative
links are retained, and new files do not share input inodes.

The producer computes the native expected tree identity from this checked
projection, validates it with the shared Ruby reader and writes the small
identity receipts last. An existing destination is never replaced; a failure
preserves diagnostic output and emits no accepted receipt. The output contains
private module data: never upload `main` as a public CI artifact or include its
contents in logs. Its two identity-only JSON files contain no module bytes.

The accepted published executor digest binds this projection and its expected
receipt together. A deployment must select that exact digest and verify its
source/module identities independently before using its receipt as expectation
for the existing init-copy/store interfaces. A mutable image tag, a fixture
receipt or a receipt generated from live r10k is not an accepted release.
This build step does not change any chart, native hook, compiler module path or
ordinary deployment behavior. The explicit chart selection below is separate;
normal catalog/repeat acceptance remains required before production enablement.

### CI compiler candidate publication

Normal executor builds now reopen their published member digest and run
`scripts/nest-compiler-candidate.py record EXECUTOR_RECEIPT OUTPUT` before
accepting the build artifacts. This rehashes all installed executor inputs,
compares the projection input inventory and validates the actual read-only
compiler tree with the native Ruby snapshot reader. Only identities are
published in `executor-receipts/CPU.compiler.json`, never module payloads.

After normal main image publication, `Deploy image` records the registry's
actual pushed mirror index digest and runs:

    python3 scripts/nest-compiler-candidate.py candidate executor-receipts \
      registry.eyrie/nest/config/main@sha256:INDEX_DIGEST \
      compiler-candidates/candidate.json

The helper verifies that exact immutable index has precisely the three
recorded Linux architecture members, each from this pipeline/source with a
distinct producing job and image. All compiler tree identities, Puppetfile
digests and complete module inventories must agree. Architecture-specific
base digests may differ. Missing members, source drift, a mutable/foreign
index, unknown platform/variant, mismatched modules or different compiler
trees refuse without an accepted candidate. Existing receipt/output files
are never replaced. Native errors are sanitized; no secrets reach summaries.

The resulting schema-1 `nest_openvox_compiler_candidate` artifact contains
source, pipeline, `current` (exact mirror index plus expected receipt), and
the checked member records. It deliberately is not a full chart selection:
there is no `retained` field, and `deployment_authorized`,
`retention_complete` and `compiler_attestation` are false. An empty retained
list must not silently discard identities required by live catalogs.
Selection/retention reconciliation, deployment sequencing, real native
catalogs and normal apply/repeat acceptance remain separate integration
obligations. This publication neither deploys a compiler nor enables hooks.
Bootstrap/partial executor publications do not emit a deployment candidate.

Run its inert fault fixtures with
`python3 spec/files/nest_compiler_candidate_test.py`. Actual published member
checks must also execute on their native architectures; unit fixtures alone
are not installed compiler acceptance.

### Isolated init copy

`ruby files/puppet-compiler-snapshot.rb SOURCE DESTINATION RECEIPT` implements
the copy boundary for a future init container. `SOURCE` is the complete selected
environment, including its actual modules. `RECEIPT` has the independently
expected frozen-tree identity described above; this command never creates that
expectation from whatever mutable bytes happen to be present. Production release
publication must still supply and verify that expectation from accepted inputs.

`DESTINATION` must be absent, outside the source, under an existing canonical
directory owned by the caller and not group/world writable. Use an isolated
per-pod volume with only the init container writing it. The helper copies files
to new inodes, preserves file/directory modes and relative contained links, and
excludes Git administration. Absolute links refuse instead of retaining a
pointer into mutable input. Special files, escaping links and a symlinked
`environment.conf` also refuse. The copied configuration is replaced by the
three constant, isolated assignments required by the native hooks. The complete
finished tree must then match the supplied expected digest and configuration.
Changed source bytes or modes cannot silently produce a new accepted identity.

On failure it emits no success receipt and preserves any partial destination;
it never cleans, adopts or replaces an existing tree, retries a fetch or changes
a running compiler. A failed init container must prevent compiler startup. The
partial tree is diagnostic state, not an accepted environment. A pod retry must
use a genuinely fresh destination/volume or stop for inspection, not erase it
blindly. The sanitized JSON success receipt establishes a checked local copy,
not a read-only compiler mount, persistent release publication or attestation.
Its `compiler_read_only_verified` and `compiler_attestation` fields remain false.

The opt-in chart integration below supplies the copy, mounts and paired hooks.
It still requires independently accepted release expectations and retention
selection. The helper is not a generic archive copier or a new source-fetch or
deployment service.

### Retained publication and native static content

`files/puppet-compiler-store.rb` adds an identity-keyed retained store:

    ruby files/puppet-compiler-store.rb publish SOURCE STORE EXPECTED_RECEIPT
    ruby files/puppet-compiler-store.rb content STORE ENVIRONMENT CODE_ID FILE_PATH

Publication requires an existing canonical, caller-owned private `STORE`
directory (mode `0700`). It takes a nonblocking exclusive local publisher lock,
copies through the checked snapshot helper and writes the supplied receipt.
It synchronizes the completed files/directories before atomically publishing
`STORE/HEX_CODE_ID/main` and `STORE/HEX_CODE_ID/expected.json`. The receipt must
already come from accepted release inputs; the publisher never derives a new
expected identity from mutable source. An existing exact release is reopened
and checked, not replaced, even if the original source subsequently changes.
Failed publication preserves its `.pending` tree and all prior releases; a
repeat refuses rather than deleting/adopting that diagnostic tree. Stores must
be on a local filesystem supporting flock, directory fsync and atomic rename.

The native content wrapper passes `content STORE` followed by Puppetserver's
environment, code ID and file path. It resolves the requested old identity,
not a mutable current pointer, checks the read-only store/snapshot and streams
only the same allowed static module paths as the paired native hook. Use the
existing fixed-snapshot `puppet-versioned-code.rb id ROOT RECEIPT` wrapper for
the compiler's current ID. Both wrappers must agree on that current snapshot;
retained old content is separate from compiler module lookup. Neither wrapper
allows a historical ID to serve today's mutable module bytes.

There is deliberately no pruning, alias promotion, network fetch or live
compiler reconfiguration in this component. Retain every published identity
until release/catalog lifetime policy explicitly permits retirement. Published
bytes must have no concurrent writer for the serving lifetime: read-only views
of a writer-owned shared store are not sufficient. The existing publication
producer and pod rollout still need to provide independent expectations,
isolated read-only mounts and that lifetime guarantee. Publication success is
not compiler attestation. This component remains disabled in production.

These requirements are acceptance obligations, not effects of merely installing
these files:

1. Publish a complete, independently checked release tree from accepted config
   and module inputs. Capture the actual served module set, including any
   deliberate pruning; the complete executor tree can legitimately differ.
2. Copy it into an isolated per-pod snapshot before the compiler starts. Do not
   mount a read-only view of the shared mutable r10k volume and call it frozen:
   the sidecar or another pod could still change the underlying bytes.
3. Mount the isolated snapshot and expected receipt read-only in the compiler.
   No concurrent writer or live pointer replacement may exist for its lifetime.
   A read-only mount is checked by the helper but does not by itself prove this
   isolation property. Hashing every invocation also cannot repair a race
   between code-ID selection and compilation.
4. Configure the compiler's environment root and global base module paths so
   it cannot load additional mutable code outside that snapshot. Both hooks
   must refer to the same snapshot. Do not install only one native hook.
5. Replace the compiler pod through the existing rollout when code changes.
   Retain old snapshots/static content for catalogs that still need them;
   preserve service availability and the existing normal deploy interface.
6. Bind the independently expected receipt to the release and native reports.
   A locally generated arbitrary receipt or successful fixture is not deployed
   compiler attestation or normal main-catalog acceptance.

The helper intentionally performs a full inventory check for every command.
Do not cache it against a mutable directory to improve performance. Measure
real module-set cost before deciding whether an immutable startup-verified
mechanism is needed. This boundary does not introduce signing or custody.

## Verification

### Explicit chart selection

`nest::service::puppet::compiler_release` is optional service Hiera data. When
absent, KubeCM emits only a non-mutating Deployment-kind check and preserves
the existing r10k deployment. When present, it is an exact schema-1 object:

- `schema`: integer `1`.
- `current`: an object with exactly `image` and `expected`.
- `retained`: an array of prior objects with exactly `image` and `expected`.

Each image must be `registry.eyrie/nest/config/main@sha256:DIGEST`, selected from
accepted publication, not a tag. Each expected object has the four receipt
fields documented above, supplied independently from the accepted release.
Duplicate code IDs, unknown fields and malformed identities refuse rendering.
Select an accepted multiarchitecture index, or constrain placement to the
architecture of an individually selected member. Never infer architecture
compatibility from a common source SHA alone.

The existing `nest::eyrie::openvox::deploy` / KubeCM rendering interface applies
the selection. Init containers copy retained releases first, then current,
into one pod-private `emptyDir`. Each uses the exact selected executor image,
a read-only root filesystem and its built projection. It must match the
independent expectation before publication. The last init verifies the entire
selected set, installs both wrappers/config together and changes ownership to
the pinned chart's service UID/GID 999. Init failure prevents compiler startup
and preserves partial pod state; no retry deletes or adopts it.

Only the compiler mounts that volume after init, read-only. Neither the r10k
sidecar nor any other pod can write it. The mutable code-volume mount is removed
from the compiler. The startup entrypoint sets the fixed environment root and
an empty base module path using the explicit server configuration directory.
The code-ID wrapper refers only to current; static content selects current or
retained by exact ID. The patch checks the pinned chart's container and mount
layout before removing anything, refusing chart-layout drift.

The original mutable `nest::puppet::deploy` preflights all selected backends and
refuses before r10k writes when any has an immutable compiler. It must not claim
a mutable code refresh updated a frozen compiler. Such a service is updated by
selecting the accepted release and running the existing KubeCM deployment,
which replaces the pod. Automatic CI selection/rollout, native catalog and
converged repeat acceptance remain integration work; do not enable this option
on an ordinary CI-managed service before that follow-through is ready.

Retained releases are private copies in each new pod, not a read-only view of
a store another pod can mutate. Keep the accepted image digests and every code
ID required by still-live catalogs in the next selection. Removing an entry
does not garbage-collect its registry image, and this feature neither grants
retirement authority nor proves release-long registry retention. Rollback
selects the previous accepted current and retains both identities, then uses
the same pod replacement. Do not restore mutable code under a historical ID.

The optional native integration check requires Python with PyYAML, Podman, the
accepted executor images and exact server image already present locally:

    python3 spec/files/openvox_compiler_pod_native_test.py \
      --manifest PRIVATE_KUBECM_RENDER.yaml --server-image IMAGE_AT_DIGEST \
      --jar-sha256 INDEPENDENT_JAR_SHA256 --output-dir NEW_LOCAL_DIRECTORY

It executes the actual rendered init commands without a source overlay, then
the paired wrappers in the server image as UID 999. It verifies server JAR
identity, isolated paths, static-content digest, wrong-ID refusal and an EROFS
write refusal. Private copied module bytes remain only in a disposable named
volume removed on exit; the output contains safe receipts, not the rendered
manifest or source payload. This is not a native JAR catalog compile, live
deployment, ordinary main apply or complete compiler attestation.

Focused public integration-contract tests:

    pdk test unit --tests=spec/files/nest_puppet_versioned_code_spec.rb,spec/files/nest_puppet_compiler_snapshot_spec.rb,spec/files/nest_puppet_compiler_store_spec.rb
    pdk test unit --tests=spec/functions/openvox_compiler_patches_spec.rb,spec/plans/puppet_compiler_deploy_spec.rb,spec/plans/puppet_management_spec.rb
    pdk validate

The producer's real-Git/input-drift fixtures run with
`python3 spec/files/nest_compiler_release_test.py`; they use the actual shared
Ruby inventory reader, not a simulated code-ID response. Its CI entry is part
of the existing update fixture job. Native-image verification additionally
projects the complete installed module set in a network-disabled, read-only
digest image with only disposable local output, never live host data.

The optional native test starts the actual pinned Puppetserver JAR, its JRuby
pool and its HTTP dispatcher inside a network-disabled, disposable Podman
container. It requires an immutable image already present locally and the
independently observed JAR SHA256:

    python spec/files/puppet_versioned_code_native_test.py \
      --image IMAGE@sha256:DIGEST \
      --jar-sha256 JAR_SHA256 \
      --output-dir NEW_LOCAL_EVIDENCE_DIRECTORY

The output directory must not exist. Only generated inert fixture files and
this source helper are mounted, all read-only; the server's generated CA and
runtime state remain in disposable tmpfs. The test exposes no host ports and
makes no production request. Its deliberately permissive HTTP authorization is
confined to container loopback with `--network=none`, never deployment policy.
The synthetic source SHA made of `a` characters is fixture data, not a source
acceptance receipt.

The native test first executes the real init copy boundary, replaces the original
mutable module input, then mounts only the copied output read-only. It verifies
real v4 and ordinary v3 catalogs carry the expected
identity, loads an actual module, verifies static-content delivery, refuses a
wrong static identity and unknown environment, observes an `EROFS` write refusal,
and compiles from the same frozen module after changing separate mutable input.
The content hook also reopens an older published identity through the real
native HTTP endpoint and verifies its different static bytes are still served
after publishing the current identity. All publication expectations in this
test are independently selected inert fixture trees, not production receipts.
It does not apply a catalog, run the agent, verify production TLS, publish a
production release, or exercise a host transaction. Its invocation, native logs and parsed
catalogs are retained for independent readback.

## Compatibility and rollback

Existing mutable deployment behavior is unchanged while selection is absent.
An explicit selection changes the compiler path and intentionally refuses the
old mutable deploy path rather than reporting stale code as deployed. Keep this
option disabled until complete publication, rollout and retention are verified.
A later deployment rollback restores the previously accepted compiler snapshot
and its matching hooks/receipt together; never point an old ID at current r10k
content. No reset, reboot, quota change or release promotion is authorized here.
