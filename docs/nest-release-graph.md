# Native same-source release graph

Current admission: executing graph compilation remains disabled. Actual
nonpublishing pipelines 11573 and 11574 rejected the former same-project
multi-project node edge with `invalid_bridge_trigger`. Lint did not prove
scheduling. The compiler now flattens member freezers into the graph child,
and the freezer, predecessor and final acceptance readers use that direct
lineage. This source has offline coverage, not live contract acceptance.
The CLI still refuses `--compile` before publishing artifacts. Standalone
frozen-input routes remain available. Remove this refusal only after the exact
flattened contracts and nonpublishing pass/fail propagation are verified;
the previously accepted status-only nesting exercise is not that evidence.

`scripts/nest-release-graph.py` extends the existing frozen-input publisher,
base discovery/binder, candidate route and final assembler. It is a GitLab CI
compiler, not an agent shell scheduler or a new update service. It does not
promote aliases, deploy configuration, reset/reboot hosts or restore backups.

This implements the same-source scheduling boundary. It does not complete the
separate old executor -> OpenBolt -> distinct successor config bootstrap, the
multi-architecture program envelope, production resource/ISA/ABI acceptance,
source-owned specialized executor admission or the host transaction lifecycle.

## Operator input

After reviewed source is installed at `main`, an explicitly authorized build
may select `RELEASE_GRAPH=true` and the GitLab file variable
`RELEASE_GRAPH_FILE`. Supported initial sources are API, web and trigger, never
push, MR, schedule, native downstream or parent pipeline. Source publication
alone does not select graph execution. Do not run a candidate build merely to
test this interface or infer build/rollout authority from these instructions.

The JSON request has exactly:

- `schema`: integer 1.
- `kind`: `nest_release_graph`.
- `expectations`: the existing complete schema-1 release expectations, including
  all known consumer rebuild/reuse/defer/retire decisions, immutable seeds,
  selected source closure, member compatibility and exact executor image.
- `executor_job`: exactly `pipeline` and `job`, positive integer identities of
  the already accepted config executor resource.
- `nodes`: one node for every rebuilt member, no reused/deferred/retired node.
  The graph is bounded to 32 rebuilt members and one executor architecture.
  Use separate architecture graphs; never relabel another architecture receipt.

Every node has exactly:

- `member`: an existing member ID; it is also the deterministic node name.
- `job_name`: the actual required native downstream candidate job name, beginning
  with `Candidate `. Select it from reviewed repository CI, not an inferred CPU
  convention. The actual pipeline must contain exactly one matching job.
- `placement`: null except for Stage 3, where it is the canonical absolute
  runner-local placement-file path used by the existing Stage 3 contract.
  This is not a file upload, dataset allocator or GUID substitution. The file
  must still match the final, rebound expectations digest when execution starts.
- `bindings`: an empty list for independently pinned seed inputs, or the complete
  set of this member's base slots. Each edge has exactly `base`, `producer`
  (another rebuilt member ID) and `artifact` (`normal`, `debug` or `image`).

For example, a fresh Stage 1 node binds both `normal` and `debug` slots to those
roles from the same Stage 0 producer. A fresh Stage 2 node binds `image` to its
Stage 1 producer's `debug`; a fresh tool binds `image` to Stage 1 `normal`.
Stage 3 uses the matching Stage 2 image/platform/compatibility. Existing recipe
CPU/variant/fresh/refresh checks apply; graph edges cannot override them.

Partial pairs, duplicate/unknown nodes, incomplete rebuilt coverage, cycles,
unsupported projects, incompatible bases, mixed architectures and variable
expansion in input are refused. Seed digests remain reviewed immutable inputs,
not guessed future output digests. No build job is emitted for reuse, defer or
retire decisions, and no new compatibility claim is made for those consumers.

## Native topology and failure handling

### Member-scoped freezer compatibility

The accepted input-producer naming contract is now either the exact legacy
name `Freeze release inputs` or `Freeze release inputs MEMBER`, where MEMBER
is the exact validated result member ID. There is no caller-supplied job-name
override, prefix match, wildcard or fallback to another member. For example,
the input for member `stage0-haswell` may use
`Freeze release inputs stage0-haswell`, but never the freezer for
`stage0-cortex-a53`.

Config's binder, native discovery and distinct-source OpenBolt bootstrap
share this contract. Discovery requires exactly one matching legacy/scoped
producer in the selected input pipeline. A legacy/scoped pair is ambiguous,
even if the bytes match. Sibling member freezers may be running: discovery
selects only this member's successful, required resource. Job names are
rechecked between the pipeline listing and exact job acquisition. All existing
source SHA, project/pipeline/job, artifact hash, result member, executor and
prepublication race checks still apply. Artifact paths and schemas are unchanged.

This is a compatibility prerequisite, not scheduler enablement. The compiler's
topology is root compiler -> config graph child containing distinct
member freezer jobs -> per-member route child -> Stage/tool native pipeline.
Each freezer waits only for its predecessor route bridges. There is no separate
config node pipeline. Each job's isolated workspace can keep the existing
`release-inputs/` artifact paths. Native discovery and final acceptance must
resolve that flattened lineage rather than the old node layer.

Stage/tool repository consumers must implement the same exact member-scoped
name admission in reviewed source before the executing graph is enabled.
All four Stage consumers and OpenBolt, PDK, Agent, Firefox, Camofox and
llama.cpp have passed independent parent acceptance of the scoped-input and
schema-2 source prerequisites. This is source/offline contract acceptance,
not native scheduling or production job-token permission acceptance. No
consumer check is bypassed here; specialized executor pins remain enforced.
The CLI remains disabled pending actual flattened-contract nonpublishing
pass/fail acceptance.
Do not replay the previously accepted status fixtures as proof of those new
contracts, and do not use real candidate builds merely to test scheduling.

The compiler job writes, fsyncs and reopens `release-graph/request.json`,
`graph.yml` and `receipt.json`. The receipt binds their byte hashes and exact
source/pipeline/job, with execution explicitly not started. Existing CI retains
only successful publication. No previous job-local directory is overwritten.

`Run release graph` includes the generated artifact as the first config child.
Each ordinary `Freeze release inputs MEMBER` job waits only on predecessor
`Release node MEMBER` bridges. Each member bridge waits on its own freezer and
includes that exact job's `release-inputs/candidate.yml` as the second and final
config child. Its direct multi-project bridge starts the Stage/tool pipeline.
There is no config node pipeline or same-project multi-project edge. Independent
siblings can run concurrently. Every bridge requires success, uses
`strategy: mirror`, and disables caller pipeline-variable forwarding.

Each freezer acquires the exact compiler artifact by successful job ID and byte
hash, verifies its running required job identity in the graph child and the
compiler -> graph edge, then resolves successful predecessor graph/freezer ->
route child -> Stage/tool edges. The graph's input pipeline is shared but every
member's input job is distinct. Legacy/scoped ambiguity, sibling substitution,
changed job identity and old node-layer lineage refuse. Unrelated running
sibling freezers do not block a successful predecessor. Volatile runner/user
metadata is not identity. Parent-pipeline route compilation is admitted only
for the exact scoped freezer job name; ordinary parent jobs remain refused.

Existing discovery rejects failed, erased, moved, retried, ambiguous, tolerated
or incomplete producer resources, outgoing leaf triggers, changed artifacts
and wrong source/executor inputs. It binds actual immutable predecessor output
references, not mutable latest-success lookups.

Immediately before publication, a graph-specific guard reacquires the parent
lineage as well as the ordinary discovery/route checks. A retried graph-parent
bridge during result acquisition cannot escape leaf-only race checks. The
node then retains the ordinary expectations, discovery evidence, candidate
route and exact input receipt before the native candidate can start.

A failed predecessor cannot admit descendants. GitLab owns status propagation;
there is no polling loop, retry API, orphan build launcher or global queue in
the compiler. Ambiguous/failed work remains a native failed pipeline. A retry
requires deliberate existing CI/operator recovery; do not replay the entire
release to manufacture missing receipts or retry an unknown host operation.

## Final graph acceptance

The generated `Accept release graph` job depends on every rebuilt node. Green
bridges alone are insufficient. It reacquires all native producer/input/result
resources, reconstructs every selected member's expected bases from the graph's
seed pins plus its actual predecessor outputs, and verifies the original frozen
closure was changed only at that member's declared base slots.

The existing assembler independently verifies the exact executor job/receipt,
all rebuilt member outputs, unique producers, paired normal/debug images,
source/compatibility/root identities and changed resources across acquisition.
Final graph lineage and original compiler bytes are read again. The job then
fsyncs and reopens `release-graph-acceptance/receipt.json`, retained on success.
The acceptance writer must itself be the unique running, required, unerased
`Accept release graph` job in that exact graph pipeline, bound to the caller's
job ID and the config source in both pipeline and commit observations. It is
reacquired immediately before publication; a missing, replaced, retried,
tolerated or completed writer refuses without publishing a receipt. Unrelated
sibling jobs and volatile display metadata do not affect this identity. The
receipt records `acceptance_job` alongside `graph_pipeline` for exact readback.
It includes the complete original graph, the assembled rebuilt subset and
explicit unbuilt consumer decisions. It is not an accepted complete release
including reused artifacts, an image existence/ISA/ABI certificate, an alias
promotion receipt or a host acceptance record.

## Source, access and rollback boundaries

Opt-in [expectations schema 2](nest-release-source-contract.md) separates the
config orchestration/input source from the exact executor build source. Schema
1 retains the same-source rule. Native graph lineage always binds the actual
config orchestration checkout; build plans/modules still come from the pinned
executor. This does not make old schema-1-only images or consumers support
schema 2, and does not enable the executing graph.

Compilation requires the actual clean `main` checkout at the graph's config
source. Native config/Stage/tool targets use their existing `main` routes;
if a branch moves away from the frozen source, the checkout/source contract
fails closed rather than silently changing the release. This interface does
not create tags or change refs. Do not compile from an uninstalled feature
branch and expect it to execute as `main`.

Artifact acquisition uses only fixed allowlisted GitLab GETs. Local reads use
existing `glab` authentication; CI uses only its ephemeral job token with the
same fixed-origin, no-redirect transport for pipeline, job, bridge and compiler
artifact reads. Public project identity is independently read unauthenticated.
This replaces inherited CI paths that still invoked unauthenticated `glab`;
it does not relax lineage checks or prove native permission admission.
`READ_PIPELINES` is required for pipeline/bridge metadata and `READ_JOBS` for
job inventories/artifacts; no permission settings change here.
Production runner job-token access and all required
registry/private module/runner-local resources must be separately admitted;
no user token is injected to make an inaccessible CI boundary look successful.
Stage 3 trust policy is source-checked before graph publication and again by
the ordinary input publisher. No private identity bytes enter the graph.

Graph and node mode fields, including partial, false and whitespace values,
suppress ordinary executor build and deployment jobs. Test-stage selection
checks reject conflicting modes. Existing nonpublishing status fixtures reject
graph fields as conflicts and cannot launch an executing graph. Default human
and ordinary managed-delivery interfaces remain unchanged without graph fields.

Rollback omits graph fields and uses the existing exact input/discovery/route
interfaces. Preserve all published inputs/results/receipts and prior digests;
never relabel old outputs, erase useful failure evidence, promote aliases or
rebuild an old release from mutable source to approximate rollback.

Offline tests exercise actual CLI acquisition with fake glab, all architecture
selections, sibling dependency fanout, explicit reuse, Stage 3 placement,
malformed modes, source/resource/lineage failures, digest-named results,
readback/no-clobber and parent/result races. Real GitLab merged-YAML dry runs
validate default isolation, whitespace guards, root/node source admission,
fixture conflicts and generated child job/needs/trigger syntax without creating
pipelines. These are not real candidate build/resource/host acceptance.

`GraphArtifactFlowTest` in `spec/files/nest_release_graph_test.py` additionally
carries the compiler function's emitted request and generated job variables
through separate disposable Git checkouts and real `--freeze-node` and
`--accept` subprocesses. The root freezer's actual projection becomes the
simulated Stage 0 input; its digest-named fixture result binds the descendant's
actual bases and projection. Final acceptance reopens both emitted inputs and
assembles those exact simulated outputs. Changed compiler bytes, a failed
predecessor and a self-consistent changed descendant policy refuse publication.
The compiler CLI is deliberately not bypassed or enabled by this test.

These GitLab resources, executor receipts and leaf outputs are explicitly fake
and confined to the disposable test. The closed fake `glab` serves only fixture
GET replies. The test performs no image build, publication, host operation or
live job-token acquisition. Run it with `python3 spec/files/nest_release_graph_test.py`;
the existing release fixture CI job includes it. This closes an offline
cross-job artifact-flow gap, not the still-required live nonpublishing contract
exercise. Stage consumers' existing status-only fixture cannot supply those
live input/result artifacts, and another status-only topology run would not
close that gap. Keep executing graph compilation disabled.

## Nonpublishing nested topology exercise

After this source is installed at `main`, the existing status fixture also
accepts `NEST_DAG_FIXTURE=nested-stage1-pass` or `nested-stage1-fail` from API
or web pipelines. Do not combine it with any build, route, bootstrap, graph,
host or executor selector. False and whitespace conflict values also refuse.
Only the selection check, nested compiler and required artifact-backed bridge
are selected; ordinary tests, executor builds and deployments are suppressed.

The compiler retains and reopens `nested-dag-fixture/child.yml` and a receipt
bound to its actual checkout, pipeline, job and child bytes. Its native config
child includes the same reviewed local CI with only the fixed
`node-stage1-pass` or `node-stage1-fail` fixture mode. That child contains the
freezer job directly, not another same-project multi-project bridge. It
compiles the second and final artifact-backed route child with one Stage 1
bridge with the existing `RELEASE_DAG=true`, `RELEASE_VALIDATE_ONLY=true` and
exact pass/fail fixture outcome. Node modes accept `parent_pipeline` source
only, so the nesting terminates
rather than compiling another graph root or a third same-project child.
Every bridge uses `strategy: mirror`, forbids tolerated failure and disables
caller pipeline-variable forwarding. No API launcher or retry loop is used.

Read back the root -> config child/freezer -> route child -> Stage 1 leaf
resources and both compiler artifacts. Passing requires successful status at
every layer. The failing fixture deliberately fails its Stage 1 leaf and must
fail every bridge and root, with no builds, publications or host actions.
Retain that intentional failed pipeline as test evidence, not a broken release
or a reason to retry the leaf. A successful pipeline creation is not acceptance.

This is a bounded supported-topology/status exercise. It is not acceptance
of the disabled graph compiler. It does not execute its input discovery,
lineage guards, candidate jobs, executor bootstrap, resource access or ISA/ABI
checks, and must not be presented as those contracts' live acceptance. It
does not replace the remaining full program or separately approved host canary.
