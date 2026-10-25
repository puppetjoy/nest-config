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

### Additive successor selection

For an already accepted immutable selection, the same helper can propose its
next selection without discarding old catalog content:

    python3 scripts/nest-compiler-candidate.py selection \
      compiler-candidates/candidate.json PREVIOUS_ACCEPTED_SELECTION.json \
      NEW_SELECTION.json

This command works outside the producing CI environment. It strictly checks
the candidate's complete source/pipeline/member/input identities and reopens
its exact registry index with the same platform/member verifier as publication.
It validates the previous chart selection and moves its current release into
the retained set, preserving every older retained entry unchanged. If the new
code ID is already selected, its expected receipt must agree exactly; that ID
becomes current and every other ID remains. Repeats and rollback proposals do
not drop the intervening release. Duplicate previous IDs, conflicting source
receipts, mutable images, missing/unknown fields and existing output files
refuse. Input/output documents are bounded; exceeding the limit refuses rather
than silently pruning retention.

The previous document must come from the independently accepted source/deployed
selection. Passing a locally invented predecessor does not establish catalog
coverage. This helper does not fetch that provenance, attest the registry's old
image retention, inspect outstanding client catalogs, accept a candidate's CI,
change Hiera or deploy. Its output is a proposal in the existing chart schema,
not permission to apply it. The selected init containers still independently
check every actual tree before a server can start.

Legacy mutable deployments and absent/null previous selections deliberately
refuse. First adoption needs its own live-catalog compatibility reconciliation;
there is no implicit bootstrap, empty-retention fallback or retirement switch.
Automatic source selection/rollout and native catalog/apply acceptance remain
open. No current service selection is changed by this command.

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
After the image's standard recursive permissions setup, the custom entrypoint
links conf.d/versioned-code.conf to the paired hook configuration on the
read-only snapshot. Do not put a read-only submount beneath the image's chown
paths: that prevents the standard startup from completing. The configuration
bytes remain immutable; only the local configuration-directory link is writable.
The code-ID wrapper refers only to current; static content selects current or
retained by exact ID. The patch checks the pinned chart's container and mount
layout before removing anything, refusing chart-layout drift.

The existing CSI-backed server volumes cannot be shared by two replacement
pods, including pods on the same node. Immutable selections therefore use a
`Recreate` Deployment strategy, explicitly clearing `rollingUpdate` during the
Helm transition: the old pod must release its mounts before the
new pod initializes. This entails a compiler interruption for every immutable
code update, not a zero-downtime rolling refresh. Confirm the selected backend's
maintenance impact before first adoption. Do not force-unmount another pod's
volumes or weaken the CSI check to work around
this constraint. The normal mutable r10k path retains its original strategy.

The original `nest::puppet::deploy` preflights all selected backends before any
writer. Its mutable r10k path refuses an immutable compiler unless the caller
supplies the exact main `compiler_candidate`. That path then performs the
additive immutable KubeCM rollout described below, not a misleading r10k refresh.
First adoption, normal native catalog/apply/repeat and release-long retention
still require integration acceptance before enabling the option.

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
identity, isolated paths, static-content digest, wrong-ID refusal and EROFS
write refusals through both the store and the linked hook configuration. It
runs the image's actual permissions script and generated hook twice to cover
startup and restart ordering. Private copied module bytes remain only in a disposable named
volume removed on exit; the output contains safe receipts, not the rendered
manifest or source payload. This is not a native JAR catalog compile, live
deployment, ordinary main apply or complete compiler attestation.

Add `--http` to that same command to start the pinned server JAR and its real
JRuby/HTTP dispatcher against the exact rendered store and wrappers. The
network-disabled container exposes no ports. Its permissive authorization is
loopback-only test configuration, never deployment policy; generated CA/runtime
state and private server logs stay in disposable tmpfs. No agent runs.

This option verifies native static HTTP delivery for each selected code ID,
including retained module library bytes, and the ordinary v3 file-content route
used by old catalogs with null code IDs. The receipt explicitly distinguishes
whether the selected library content differs between releases, including a file
absent in the previous release: equal bytes alone cannot prove historical
content routing. Missing historical files and an unknown identity must refuse. A v4
catalog request for the existing forbidden `bolt` client must execute the actual
immutable main manifest's refusal. That is a failed compile, not a successful
host catalog or native compiler attestation. Only statuses, content digests and
booleans leave the container; no private module bytes, catalog or server log is
retained. This proves route compatibility, not coverage of outstanding client
caches, production TLS or readiness for first adoption. Keep production hooks
disabled until selection/CI rollout and normal main apply/repeat are integrated.

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

## Legacy first-adoption cache reconciliation

A mutable deployment has no accepted previous immutable selection. Do not
invent one or treat an absent cache ID as proof that no client needs content.
The read-only task `nest::compiler_catalog_cache` observes the native JSON
cache at the agent's actual `client_datadir/catalog/CERTNAME.json`:

    bolt task run nest::compiler_catalog_cache --targets owl --run-as root \
      'expectations={"hostname":"owl","certname":"owl","server":"puppet.eyrie"}'

It binds hostname, certname, configured server and unchanged boot, reads the
same root-owned trusted regular file twice, and emits only identity
headers and a digest. It never loads/applies a catalog, synchronizes plugins,
contacts a compiler or deletes caches. Missing `code_id`, missing/unsafe or
changing caches, non-main caches and malformed/duplicate JSON refuse. A
present JSON null `code_id` is explicitly legacy, not a missing observation.
The native root:root 0660 cache mode is supported; world write, writable
non-root groups and a symlinked cache file refuse. Ancestor directories remain
the existing agent's trusted runtime boundary, including its daemon-owned
vardir. This read is an observation, not a tamper-proof cache attestation.

Historical mutable Nest compilers emitted abbreviated Git configuration versions.
For an explicitly present null `code_id`, the observer and adoption reader accept
7–40 lowercase hexadecimal characters and preserve the exact version token. They
never resolve or expand it, bind it to a release source, or infer historical
content preservation. A non-null immutable code ID still requires a full
40-character source matching its independently accepted expected receipt. Missing
code IDs, malformed versions and shortened immutable sources continue to refuse.
Do not run a new host apply merely to replace a historical version abbreviation.

Keep the original inventory-backed invocation receipts and an explicit scope
JSON object with `schema: 1` and a nonempty `clients` array. Each client has
exactly `hostname`, `certname` and `server`. Collect the sanitized successful
task values in an observations JSON array; retain failures rather than
silently removing their clients from the scope. Known prior releases are an
array of the accepted `{image, expected}` objects, not a fabricated previous
selection. An explicitly empty array means none are supplied, not that global
retention has been proven.

    python3 scripts/nest-compiler-adoption.py CANDIDATE.json SCOPE.json \
      OBSERVATIONS.json KNOWN_RELEASES.json NEW_PROPOSAL.json

This non-deploying command requires one observation per exact scoped client,
at most fifteen minutes old and not in the future. Every non-null code ID must
be covered by the candidate or a supplied prior release, with matching source.
All supplied prior identities remain retained, including those not observed in
this bounded scope. The candidate's actual multiarchitecture index is reopened
and checked against its producing receipts before output. Existing output is
never overwritten. Observations and submitted release objects are evidence,
not trusted attestations or proof of their own provenance.

The output is an adoption proposal, deliberately not a chart selection or
deployment approval: its `selection` member is the proposed selection. It lists
legacy clients and explicitly leaves global cache coverage, historical legacy
content binding, retention completeness, deployment authority and compiler
attestation false. Null-ID catalogs use the ordinary v3 current-content route;
that compatibility does not preserve historical bytes or prove a successful
normal main apply/repeat. Reconcile all relevant consumers and retained images,
then finish automatic selection/CI rollout and normal acceptance before enabling
the paired production hooks. This command does not close those obligations.

Focused checks also include:

    python3 spec/files/nest_compiler_adoption_test.py
    pdk test unit --tests=spec/tasks/nest_compiler_catalog_cache_spec.rb,spec/tasks/nest_update_catalog_report_spec.rb

## Compatibility and rollback

### Additive routine CI rollout

The ordinary main `Deploy environment` job now waits for the same pipeline's
`Deploy image` candidate and uses the `puppet-code-deployment` resource group.
When a selected backend is still mutable, its r10k and cache-expiry behavior is
unchanged. When already immutable, the plan requires an annotated selection and
dispatches through `scripts/nest-compiler-rollout.py`. No current production
selection is enabled by installing this integration.

The chart records its complete declared selection in the pod template annotation
`nest.eyrie/compiler-selection`. This is declaration, not attestation. The helper
also checks native init images, expected receipts, final current identity,
pod-private storage and compiler-only read-only mounts. A missing annotation,
legacy deployment or partial mode change refuses automatic first adoption.

    python3 scripts/nest-compiler-rollout.py CANDIDATE.json test \
      rollout-evidence/compiler/test --check

`--check` is read-only and creates no files. Without that flag, the default is
render-only: the existing `nest::eyrie::openvox::deploy` / KubeCM interface renders
the selected chart into a new private local output directory. The helper uses an
invocation-specific Hiera override, preserving the original hierarchy and eyaml
handling; it never edits tracked Hiera or deployed Puppet code. The rendered
Deployment must contain the exact additive selection and native mount/init
layout. Helm render output and native logs can contain private data and must not
be attached or uploaded as public CI artifacts.

`--deploy` additionally reinspects the predecessor UID and resource version,
invokes the same existing KubeCM deployment, waits for the exact Deployment
rollout and reopens its selected identities and ready replica counts before
writing `receipt.json`. Native failure leaves the private output in place and
does not emit a success receipt. Existing output is never overwritten or adopted.
Use a fresh directory only after diagnosing the previous attempt; this is not an
automatic retry or rollback loop.

Each successor retains every previously declared identity. Same-ID source
disagreement refuses. The exact multiarchitecture candidate is reopened and
all retained image references must still be readable. Main source must still be
the current remote main; CI context, when available, must match the candidate's
source and producing pipeline. The current-main check reads the canonical
public `nest/config` HTTPS repository
outside the local checkout. It does not require local `origin` or the external
Git administration of a linked worktree to be mounted into the Bolt container.
The CI resource group serializes normal writers; the resource-version recheck
detects intervening manual writes but is not an
atomic cluster-wide lock. Manual chart writers still require coordination.

Only sanitized `receipt.json` paths are CI artifacts. Readiness is not a normal
host catalog/apply/repeat, compiler attestation or registry retention lease; the
receipt keeps those acceptance fields false. First-adoption cache coverage and
registry lifetime remain required before enabling production. The public
`nest::kubernetes::deploy` adapter also renders and guards an already immutable
OpenVox stack before writes, refusing mutable/stale Hiera that would lose or
change any declared identity. Render-only calls do not deploy or recurse into
that guard. Initial mutable stacks keep their normal behavior.

Manual redeploy/rollback must carry the latest complete additive
selection, including identities introduced by later CI; do not use stale source
Hiera as implicit retirement authority. No pruning or first-adoption switch is
performed by this helper.

Focused failure tests additionally include:

    python3 spec/files/nest_compiler_rollout_test.py

Existing mutable deployment behavior is unchanged while selection is absent.
An explicit selection changes the compiler path and intentionally refuses the
old mutable deploy path rather than reporting stale code as deployed. Keep this
option disabled until complete publication, rollout and retention are verified.
A later deployment rollback restores the previously accepted compiler snapshot
and its matching hooks/receipt together; never point an old ID at current r10k
content. No reset, reboot, quota change or release promotion is authorized here.
