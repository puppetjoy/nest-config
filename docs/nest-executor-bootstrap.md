# Distinct OpenBolt to config executor bootstrap

The config executor build and optional native successor route accept an exact
successful native OpenBolt result without relabeling the old executor's release
as the new config source. This
extends the existing `.template` build and schema-2 executor receipt. Its explicit
artifact-backed child uses the existing GitLab trigger mechanism, not a service
or shell orchestrator, and cannot trigger config -> Bolt -> config recursively.
The ordinary same-source binder, discovery, assembly and envelope contracts are
unchanged; do not bypass their source checks to model this separate boundary.

This is input acquisition and candidate executor publication, not the complete
release DAG, production resource/ISA/ABI acceptance, alias promotion or rollout.
Installing it does not authorize a new OpenBolt or OS build merely for evidence.

## CI selection

On the exact selected successor config revision, use the existing API, web,
native pipeline or trigger source with:

- `EXECUTOR_BOOTSTRAP=true` and `EXECUTOR_ONLY=true`.
- `BUILD=haswell`, `BUILD=cortex-a53` or `BUILD=sifive-u74`, exactly one native
  executor architecture. The selected job supplies its matching `CPU`.
- `RELEASE_BOOTSTRAP_FILE`, a GitLab file variable containing the request below.

No caller `BOLT_IMAGE` override is permitted in this mode. Ordinary builds without
bootstrap fields retain their existing default/override behavior. Tag, push, MR,
schedule and unbound parent-pipeline bootstrap execution are refused. Partial, false,
malformed or conflicting selection cannot fall through to ordinary executor
builds or either deployment job. The Test-stage selection job fails before any
Build-stage action. Existing isolated status-fixture mode still suppresses all
executor/deployment jobs; do not mix it with executing modes.

The helper runs before registry login, directory creation or build commands:

```sh
python3 scripts/nest-executor-bootstrap.py --check-selection
python3 scripts/nest-executor-bootstrap.py --ci-base
```

The first validates selection only. The second reads the exact submitted file,
checks the clean real CI checkout/project/source/job/CPU identity, acquires the
OpenBolt inputs and publishes a new local `executor-bootstrap` directory. It
prints only the acquired immutable OpenBolt reference for the existing build
script. Static diagnostics and exit 1 indicate operational refusal; argument
errors return 2. Neither helper invocation builds, triggers or retries anything.
`--ci-base` without bootstrap fields prints the existing ordinary base selection
and does not create a bootstrap directory.

## Native successor route

After the separately approved OpenBolt producer has completed, select
`EXECUTOR_BOOTSTRAP=route` on an API/web/trigger pipeline at the exact successor
config revision on `main`. Keep `EXECUTOR_ONLY=true`, one native `BUILD` CPU and
the same `RELEASE_BOOTSTRAP_FILE` request. This selection authorizes an actual
successor executor build through the existing CI, so do not launch it merely to
manufacture acceptance evidence. No new OpenBolt or OS build is triggered.

`Compile executor bootstrap` runs `--compile-route`. Before publishing anything,
it checks the clean source/job/CPU identity and independently acquires the whole
old-executor/OpenBolt boundary twice. It retains the canonical original request,
acquired evidence and generated child YAML with fsync, no-clobber and readback.
Compilation itself performs only authenticated reads and local publication.

`Run executor bootstrap` consumes that exact artifact with `strategy: mirror`.
Its pipeline/YAML variable forwarding and inherited variables are disabled. The
generated child includes this same revision's CI with exactly six fixed variables:
`EXECUTOR_BOOTSTRAP=true`, `EXECUTOR_ONLY=true`, `BUILD`, and the exact compiler
`RELEASE_BOOTSTRAP_PIPELINE`, `RELEASE_BOOTSTRAP_JOB`, `RELEASE_BOOTSTRAP_SHA256`.
It never forwards the file variable's path, credentials, other selection modes
or a mutable image alias. Same-project `trigger:project` is not used; this is one
artifact-backed child, leaving no recursive config -> Bolt -> config trigger.

The child admits artifact selectors only as a complete set from `parent_pipeline`,
never alongside a file variable. Before its registry/build commands it verifies
the exact successful compiler job, raw request digest and required native parent
bridge's source/project/main-ref/child identity. The parent must originate from
API/web/trigger; the child must have no bridges. It independently acquires the
original OpenBolt evidence and reopens the route before retaining the base.
The retained bootstrap input additionally contains `route`, with exactly
`pipeline`, `job`, `sha256`. The ordinary schema-2 installed-executor receipt is
unchanged. Partial selectors and conflicting modes cannot fall through to normal
executor or deployment jobs. Downstream failure propagates to the parent.

The completed-successor reader accepts this child only by independently reopening
the retained route's compiler and its now-successful native bridge, in addition
to the original old/new artifact checks. An unrelated green child or copied route
receipt cannot substitute. Missing job-token access fails without another identity.
Actual production permissions and native bootstrap execution remain unproven.

This closes scheduling of the successor from a completed predecessor, not automatic
construction of the preceding OpenBolt release or the complete release graph.
No aliases, served Puppet code, hosts or ordinary builds change in route mode.
Rollback stops selecting `route` and preserves all predecessor/successor artifacts.

## Native predecessor discovery in route mode

The existing `EXECUTOR_BOOTSTRAP=route` compiler also accepts a schema-1
`nest_executor_bootstrap_discovery` object in `RELEASE_BOOTSTRAP_FILE`. There
are no new CI variables or trigger services. Its fields are exactly `schema`,
`kind`, `successor_source`, `successor_cpu`, `config_source`, `bolt_source`
and `producer`:

- Successor source and CPU have the same meaning as the exact request below.
- `config_source` is the exact 40-character prior config source. It may equal
  the successor revision. `bolt_source` is the exact OpenBolt source; neither is a ref.
- `producer` is the existing native discovery selector, with exactly `project`
  (`nest/tools/bolt`), `member`, `root_pipeline`, `input_pipeline`, `bridge`
  and `job_name`. The positive integer root identifies the config pipeline
  containing the completed direct OpenBolt bridge. The input pipeline identifies
  its original unique freezer. For a standalone frozen route these are the
  artifact-backed route child and its input-publishing parent, respectively.
  Use actual completed identities, not predicted or latest-success resources.

As in ordinary discovery, the config root may still be running while unrelated
jobs finish. Its selected required bridge and the entire OpenBolt leaf must have
succeeded. This is exact-edge acceptance, not whole-root or release acceptance.

The compiler discovers the actual downstream pipeline, member/input jobs and
hashes of their original artifact bytes using the existing bounded reader. It
then performs the full independent old-executor/OpenBolt acquisition. Exact
native parent/child/source/required-success relationships, complete job inventories,
artifact hashes and source closure are reacquired before local publication.
Malformed static selectors refuse before any GitLab read. No new permission,
credential fallback, mutable alias or artifact format for OpenBolt is introduced.

The retained `request.json` is the ordinary resolved bootstrap request with an
optional `native` object containing exactly `config_source`, `bolt_source` and
the original native `producer` selector. That object is covered by the canonical
request hash sent to the child. `discovery.json` additionally retains the original
submitted request and edge observation. The child independently reopens the native
edge before and after old-executor acquisition, and retains its observed identity
as `native_edge` in the bootstrap input receipt. Completed-successor acceptance
reopens this same edge rather than trusting the compiler's stored discovery or
silently dropping native provenance. A changed bridge retry refuses, even when
it points to the same successful output. Explicit requests without `native` retain
their existing schema and byte shape; older readers refuse the added field.

Only the route compiler accepts the discovery object. Direct `--ci-base` calls
and successor acceptance take the resolved `nest_executor_bootstrap` request,
including `native` when present, not an unresolved discovery object. All generated
files retain the existing no-clobber/fsync/readback behavior. The six child variables
and mirror trigger are unchanged. Compilation does not start a pipeline, and
selecting the route in CI still requires separate build authority.

This closes manual job/hash copying between the already completed prior native
OpenBolt route and successor compilation. It does not schedule the preceding
OpenBolt build, enable the full release graph, prove production job-token access
or resource/ISA/ABI compatibility, or authorize a build merely for evidence.

## Exact bootstrap request schema 1

The request has `schema`, `kind`, `successor_source`, `successor_cpu`,
and `producer`, plus only the optional `native` object described above:

- `schema` is integer 1; `kind` is `nest_executor_bootstrap`.
- `successor_source` is the exact new config Git SHA. It must match the actual
  clean checkout, not a mutable branch name. Rebuilding the same config revision
  against a newly completed OpenBolt image is supported. The successor pipeline
  and job must differ from both prior config input and executor resources;
  publication and completed-successor acceptance enforce that boundary.
- `successor_cpu` is the exact selected native executor CPU above.
- `producer` uses the existing base-binding selector with exactly `project`,
  `pipeline`, `job`, `member`, `input_pipeline`, `input_job`, `input_sha256` and
  `result_sha256`. Project must be `nest/tools/bolt`; positive integer identities
  name actual jobs/pipelines. The two bare lowercase SHA256 values bind the
  original input and result file bytes, not reserialized JSON or the ZIP archive.

Select these values from the already successful, separately approved OpenBolt
producer. Do not predict a future result, use latest-success lookup, fill missing
evidence by rebuilding or claim that this request is new build authorization.
The original input job must be named `Freeze release inputs`. Existing legacy
and digest-named member results are supported through the bounded ZIP reader.

## Exact prior boundary and successor publication

Acquisition independently checks:

1. The original frozen input byte hash and complete expectation/source/consumer
   schema. The selected member must be a rebuilt server OpenBolt with exactly the
   selected executor CPU; another tool, variant or reused member cannot substitute.
2. The exact successful unerased input job and OpenBolt producer source/pipeline/
   job/archive. The whole OpenBolt pipeline must have succeeded as a native
   downstream, with no tolerated/incomplete jobs and no outgoing trigger bridge.
   A green result job in a failed pipeline is not acceptance.
3. The original result's input digest, member, source, artifacts and embedded
   schema-2 old-executor receipt. The old executor's actual successful job and
   independently read receipt must match; no future successor receipt is needed.
4. The output must be an immutable architecture OpenBolt image under
   `registry.gitlab.joyfullee.me/nest/tools/bolt/`. Jobs, original artifact bytes,
   executor receipt and native pipeline inventories are reacquired before use.

Only fixed allowlisted GitLab GETs are used through existing `glab` authentication.
No token, caller URL, private identity content, job trace, mutation or polling
endpoint is introduced. Equivalent runner/job-token access is not assumed: missing
access must fail rather than injecting a user token or claiming fixture success as
production access acceptance. Free-text prior expectations are retained as input
data, not secret-scrubbed; review/sanitize them before sharing artifacts.

`executor-bootstrap/receipt.json` retains the separate old inputs/result/executor
and new source/job/CPU/base identity, with explicit `build=not_started`,
`image_compatibility_verification=not_performed` and no promotion authorization.
`bolt.ref` contains the exact immutable base reference. Both files are no-clobber,
fsynced and reopened before the helper returns. CI retains them with the ordinary
executor receipts on successful publication; they are not a build-success receipt.

The existing build pulls that exact digest, refuses a different resolved reference,
and passes it to `Containerfile`. The image's own installed input/module checks
produce the ordinary schema-2 receipt at the new config source. Before that receipt
is written, its actual base/source/CPU/pipeline/job must match the retained bootstrap
input. This proves the measured installed base matches acquisition; it does not
certify ISA/ABI or every resource needed by future consumers.

Bootstrap builds publish only the unique existing executor image and receipt.
They do not update CPU aliases, the aggregate `latest` manifest, Puppet code or
live hosts. Ordinary managed tooling delivery retains its existing behavior.
A later consumer must use the exact new executor job/digest after independent
acceptance. Firefox, Camofox and llama.cpp source-owned executor pins are unchanged.

## Accepting the completed successor

After a separately authorized bootstrap build has completed, use the existing
config checkout and authenticated GitLab reads:

```sh
python3 scripts/nest-executor-accept.py --successor /absolute/successor.json
python3 scripts/nest-executor-accept.py --successor /absolute/successor.json \
  --output-dir /existing/canonical/artifact/directory
```

The request fields are exactly `schema` (integer 1), `kind`
(`nest_executor_successor_request`), `bootstrap` (the complete original schema-1
bootstrap request above), and `successor`. The latter has exactly:

- `pipeline` and `job`: positive integer identities of the completed config
  successor pipeline and its single `Build CPU` job.
- `image`: the exact immutable config architecture image selected for acceptance.
- `executor_sha256`: bare lowercase SHA256 of the original
  `executor-receipts/CPU.json` bytes from that job.
- `bootstrap_sha256`: bare lowercase SHA256 of the original
  `executor-bootstrap/receipt.json` bytes from the same job.

Select these from the actual successful build, never predict them or use a
latest-success selector. Missing prior artifacts require diagnosis, not a new
build merely for evidence. An ordinary nonbootstrap executor has no bootstrap
receipt and cannot substitute, even if its version/source happens to match.

The helper validates every static selector before acquisition. It requires a
successful API/web/pipeline/trigger successor, or an independently route-bound
parent-pipeline successor, with no outgoing bridges, exactly
one selected architecture build, no deployment jobs and no failed, erased or
tolerated jobs. The independently read executor schema, source, CPU, job and image
must match. It reacquires the entire original old-executor/OpenBolt boundary using
the original bootstrap request, compares it to the successor's retained receipt,
and binds the successor's recorded installed base to the exact OpenBolt image and
`bolt.ref` bytes. Old and new build receipts stay distinct even when their config
Git revision is unchanged. Neither receipt is relabelled as the other build.

The complete acquisition runs again before acceptance; changed jobs, inventory,
source or artifact bytes refuse rather than following retries. Only two exact
config bootstrap artifact paths extend the existing GET allowlist. The helper
uses the existing glab/job-token reader without switching identities on failure;
production job-token permission for this particular boundary remains unproven.

Default mode prints only a digest and readback status, writing no files. Optional
retention uses the existing content-addressed, no-clobber, fsync/readback publisher
and retains the original request plus old/new evidence in one bounded file.
The request may then be removed without losing the retained evidence. Exit 0 is
artifact acceptance and any requested local readback, 1 is static operational
refusal, and 2 is malformed command arguments. No build, trigger, registry pull,
alias update or host operation is performed.

This accepts native successful jobs and exact artifact relationships, not image
resource/ISA/ABI compatibility or fresh local execution. Those fields remain
explicitly `not_performed`, and `promotion_authorized` stays false. The existing
successful build's schema-2 receipt records its own installed-source checks; the
new reader does not present that as its own image execution. Retained free-text
prior inputs still require sanitization before public sharing.

## Tests, remaining work and rollback

Offline tests exercise all three native architecture boundaries, raw/digest-named
results, old/new source separation, exact failed/erased/moved jobs, independently
changed executor evidence, failed/non-native/looping OpenBolt pipelines, hidden
failures, selection conflicts, read races, no-clobber/readback failure and real
CLI acquisition with fake glab. Fake Podman tests bind actual successor input
observations before writing a schema-2 receipt. They build/publish nothing.
Real GitLab merged-YAML dry runs verify admission and ordinary compatibility
without creating pipelines or artifacts.

Native discovery tests exercise every executor CPU, exact/digest-named results,
complete static pre-acquisition refusal, changed/failed/erased native resources,
bridge retries during acquisition, real compiler CLI retention with fake glab,
and independent native-edge reopening during completed-successor acceptance.
These are isolated fixtures, not actual OpenBolt or successor production builds.

The completed-successor tests exercise all three architecture selections,
independent old/new acquisition, digest-named prior results, failed/erased/changed
resources, incorrect installed bases, relabelled retained receipts, static
pre-acquisition refusal, exact artifact allowlisting and a real CLI/fake-glab
retention/readback after producer exit. They are isolated fixtures, not native
bootstrap or production permission acceptance.

The optional route now schedules a successor from an already completed OpenBolt
boundary. The full native graph must still schedule the preceding old-executor
to OpenBolt boundary and freeze each descendant after actual predecessor success.
Automatic full graph generation, later source-owned executor admission,
production permission/resource/ISA/ABI checks, full release policy/promotion and
host transaction lifecycle remain open. No actual new candidate bootstrap is
run merely to claim this interface is operationally proven.

Rollback omits both bootstrap fields and retains all original input/result/
executor receipts and digests. Do not relabel an old result at the new source,
promote an alias automatically, delete prior images or replay a completed build.
The first destructive host canary remains separately Joy-gated.
