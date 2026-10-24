# Frozen publication to native candidate routing

The existing `Freeze release inputs` job can now compile one explicitly selected
member into an artifact-backed GitLab child pipeline. The child contains a single
required multi-project bridge to the existing Stage or tool candidate entry.
Both bridge layers use `strategy: mirror`: a failed freeze cannot start the
child, and a failed required downstream pipeline cannot produce a successful
route. No script starts a pipeline or polls a shell orchestration loop.

This is the publication-to-member boundary, not the complete release graph.
Automatic predecessor scheduling, distinct accepted old-executor -> OpenBolt ->
new-executor bootstrap, production artifact/job-token permissions, resource/ISA/
ABI admission, full graph assembly and host lifecycle integration remain open.
Do not call this optional route an end-to-end release or use it to manufacture
candidate artifacts for verification.

## Explicit selection

Use the existing config input pipeline on the exact selected config source with
`RELEASE_INPUTS=true` and exactly one of the existing file variables
`RELEASE_EXPECTATIONS_FILE` or `RELEASE_DISCOVERY_FILE`. The latter first acquires
and binds actual predecessor results using the existing discovery contract.

Candidate execution is additional opt-in input, not an implication of freezing:

- `RELEASE_ROUTE=true` selects this executing route.
- `RELEASE_ROUTE_MEMBER` selects one existing `rebuild` member ID in the frozen
  matrix. It cannot introduce an extra member or select a `reuse` consumer.
- `RELEASE_ROUTE_EXECUTOR_PIPELINE` and `RELEASE_ROUTE_EXECUTOR_JOB` are the exact
  successful architecture executor producer identities. These are decimal IDs,
  not a latest-success reference, user token or caller URL.
- For Stage 3 only, `RELEASE_ROUTE_PLACEMENT` is the canonical absolute path to
  the existing local placement file on the selected downstream build runner.
  The route does not upload a private identity source, invent placement/GUIDs,
  create storage, or prove that the file exists remotely. The Stage 3 consumer
  independently validates it before building. Variable expansion in this path
  is refused.

Supported route destinations are the existing Stage 0/1/2/3 and OpenBolt, PDK,
Agent, Firefox, Camofox and llama.cpp projects. A route transmits the member's
exact CPU, variant, platform and host selection where applicable. It does not
broaden a destination's supported recipe/CPU matrix: the downstream source
validation and candidate rules remain authoritative and refuse invalid recipes.
In particular, Firefox, Camofox and llama.cpp retain source-owned exact accepted
executor pins. A different/new executor cannot bypass those pins through this
route; later reviewed admission updates and compatible source closure are still
required before those members can join a new release generation.
Stage 0 receives no variant selector; Stage 3 clears the inherited `HOSTNAME`
selector and uses the frozen host identity.

Only explicit API, web, trigger and native pipeline sources are admitted. Push,
MR, schedule, tag and parent-pipeline entry refuse executing selection. Partial,
malformed or conflicting routing flags fail the selection check. Any nonempty
routing field suppresses ordinary config executor build and deployment jobs,
including on `main`, so malformed input cannot fall through to a tooling rebuild.
Ordinary source validation/test jobs still run. With no routing fields, existing
source, managed executor and input-only behavior is unchanged. Fixture mode
suppresses the route completely.

Direct nonexecuting selection validation is:

```sh
python3 scripts/nest-release-route.py --check-selection
```

It only checks the environment and returns 0 for an admitted selection or 1
with a static diagnostic. It does not publish artifacts, build or trigger.

## Publication, native execution and discovery

The input publisher independently reads the selected executor job, its schema-2
receipt and architecture/source/image/module declarations using the existing
allowlisted GitLab reader. It reacquires them before publication; failed, erased,
wrong-source, wrong-architecture or changed resources refuse before the output
directory is created. This uses the existing `glab` authentication path. A CI job
without equivalent read access must fail; do not inject a user token or treat
fixture success as production job-token admission.

Failed allowlisted GitLab reads emit one sanitized JSON diagnostic on stderr,
`kind=nest_release_gitlab_read_failure`, before the caller's ordinary refusal.
`operation` is only `project`, `job` or `artifact`; `failure` is a fixed HTTP
status classification, `command_failed`, `command_unavailable`, `timeout` or
`oversized_response`. Paths, server bodies, raw command stderr and credentials
are never included. This is failure localization, not permission proof: the
reader does not retry, switch credentials, expand its endpoint allowlist or
accept missing job/receipt evidence. Unknown or conflicting HTTP diagnostics
remain `command_failed`. Successful reads preserve their exact bytes and do
not emit this diagnostic.

After any predecessor discovery, an executing route projects `expectations.json`
to exactly its selected `rebuild` member. Source and executor pins, member content
and policy reasons are unchanged. Other active consumers become deferred with no
members in this execution projection; existing inactive decisions remain intact.
The complete post-discovery matrix and all original decisions are retained in
`release-inputs/closure.json`. The provenance sidecar's `member_projection` binds
that artifact's SHA256, selected member and projected expectations digest. Graph
acceptance reconstructs this exact projection from the original request and actual
predecessor outputs; it does not accept arbitrary leaf input reductions. Plain
input-only publication remains unprojected and has no closure sidecar.

The publisher hashes the actual projected `expectations.json` bytes. It emits
`release-inputs/candidate.yml` as JSON (valid
YAML), alongside the existing input artifacts. The schema-1 input `receipt.json`
remains unchanged: downstream consumers compare its exact fields. A separate
`provenance.json` (`schema=1`, `kind=nest_release_input_provenance`) binds the
input receipt bytes with `input_receipt_sha256`; its
`candidate_route` binds the generated bytes' SHA256 and selected member and says
`execution=not_started`. Files are fsynced and individually reopened before the
input job succeeds. A failed readback cannot return success or overwrite a prior
publication; only successful input jobs upload these artifacts.

`Route frozen candidate` then includes that exact job artifact. The generated
child admits only the `parent_pipeline` source and has no shell commands,
deployment job or outgoing config executor bridge. Its `Build frozen member`
bridge sends only explicit public candidate pins, with pipeline-variable
forwarding disabled and inherited variables disabled. The pins contain the
actual input producer job ID, frozen-byte digest and independent executor job
and immutable image. Arbitrary caller variables, credentials, source paths and
policy reasons are not forwarded. The source-controlled input receipt remains
truthful: compiling a bridge is not runtime acceptance, resource verification,
release promotion or host authorization.

The downstream bridge targets the existing `main` branch. Before executing any
build, existing destination validation compares its actual checkout with the
frozen source SHA. A moving branch cannot silently relabel a different source:
it refuses. The route does not invent a GitLab SHA-ref trigger guarantee.

For subsequent discovery/assembly, distinguish the two config pipelines:

- `input_pipeline` is the original input publication pipeline containing the
  unique `Freeze release inputs` job.
- `root_pipeline` is the actual generated config child containing the direct
  `Build frozen member` bridge. Obtain it from the original pipeline's actual
  `Route frozen candidate` downstream readback, never from guessed/latest IDs.
- `bridge` is `Build frozen member`; `job_name` remains the destination's exact
  native candidate job name. The ordinary discovery/binder checks all identities
  and original bytes, including when the input and bridge pipelines differ.

A route retains a complete matrix but sends only its explicit member to execution.
Unrouted members are not completed outputs. No future digest is predicted and no
predecessor input/result is rewritten. The route does not advance a release
alias, reset/reboot a host, retry a candidate, perform backup/restore or clean up
storage. Build execution itself still requires the approved release scope;
installing this interface is not new build or disruptive-canary authorization.

## Nonexecuting Stage 0 input observation

`RELEASE_ROUTE=verify-inputs` uses the same freezer, exact executor acquisition,
member projection, closure, raw-byte digest and artifact-backed native bridge.
It accepts only a Stage 0 server `refresh` member in `nest/stage0`. All other
route parameters and conflicting-selector refusals remain unchanged. This value
is exact; malformed values never fall back to candidate execution.

The generated bridge is `Verify frozen inputs`, not `Build frozen member`.
It sends `RELEASE_VERIFY_INPUTS=true`, `RELEASE_VALIDATE_ONLY=true` and
`RELEASE_DAG=true`, with the exact frozen member/input/executor pins. It never
sends `RELEASE_CANDIDATE`. Both native bridge layers still mirror failure and
disable pipeline-variable forwarding. For compatibility the generated artifact
is still `release-inputs/candidate.yml`; the provenance sidecar uses the distinct
`input_verification_route` key rather than claiming a candidate route.

Stage 0's supported `--verify-inputs` entry reacquires actual config resources
with its own job token and invokes installed read-only preparation. It emits
only `release-contracts/MEMBER.json`, with kind
`nest_release_input_contract_observation`. It does not run a producer build,
reserve an attempt, publish images or emit `release-results`. Its observation
is not a member result and cannot satisfy ordinary discovery/assembly. No
predicted image output or status-only fixture is substituted for real inputs.

This optional route supports native job-token integration verification, not
full flattened graph acceptance, image/ISA/ABI compatibility, bootstrap closure,
release promotion or host authority. Production graph `--compile` remains
refused until its separate complete acceptance contract is exercised.

## Verification and rollback

Offline tests exercise strict source/conflict selection, independent executor
faults and acquisition races, every destination's field routing, original
input/discovery publication, final bound input hashing, failed output readback,
no-clobber behavior, and the real publisher CLI with a fake allowlisted GitLab
reader. Current CI selection is additionally checked with real GitLab merged-
YAML dry runs; these do not execute candidates or prove runtime permission.

Rollback omits all `RELEASE_ROUTE*` fields and retains the original explicit
input-only interface. Keep original input/result/receipt artifacts and accepted
executor digests. Never replay an already completed candidate or host operation
to repair missing evidence. Removing this route does not change release aliases,
backup generations, boot selection or existing transaction state.
