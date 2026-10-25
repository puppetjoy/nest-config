# Native bridge and member discovery

`scripts/nest-release-discover.py` resolves direct `nest/config` multi-project
bridges to their actual downstream pipelines and member jobs, then invokes the
existing exact predecessor binder. It removes manual copying of result job IDs
and artifact hashes at this boundary. It does not generate or start the full
release graph, freeze CI inputs, build images, promote aliases or operate hosts.

## Supported invocation

From the config root, using the existing authenticated `glab` installation:

```sh
python3 scripts/nest-release-discover.py --discovery /absolute/discovery.json
python3 scripts/nest-release-discover.py --discovery /absolute/discovery.json \
  --output-dir /existing/canonical/artifact/directory
```

Without `--output-dir`, the command performs only authenticated GETs and prints
an acceptance summary. With it, the existing manifest publisher atomically
retains and reopens two content-addressed files: the complete provenance package
(`path`) and directly consumable expectations (`expectations_path`). The latter
can be reviewed and separately supplied to `Freeze release inputs` as
`RELEASE_EXPECTATIONS_FILE`. Neither file is a release pointer or authorization.
A failure between publications can leave an unselected local file, but cannot
produce a successful readback summary or overwrite a previous accepted artifact.
Identical requests may reuse identical retained content without replaying a job.

Exit 0 means acquisition, binding and requested local readbacks passed. Operational
refusal returns 1 with a static diagnostic; malformed command arguments return 2.
Native stderr, raw API responses and supplied free text are not printed. Retained
expectations and selected job/bridge names still require ordinary sanitization
before public sharing; valid JSON is not a secret scrubber.

## Discovery request schema 1

The fields are exactly `schema`, `kind`, `expectations`, `executor_job`,
`producers` and `bindings`:

- `schema` is integer 1 and `kind` is `nest_release_base_discovery`.
- `expectations`, `executor_job` and `bindings` have the existing schema described
  in [exact predecessor base binding](nest-release-base-binding.md). Architecture,
  source closure, consumer decisions, complete base slots and normal/debug pairing
  remain enforced. Bootstrap phases cannot be relabeled as the same config source.
- `producers` maps one to thirty-two release-local predecessor names to selectors.
  Each selector has exactly `project`, `member`, `root_pipeline`, `bridge`,
  `job_name` and `input_pipeline`.
- `project` is a supported Stage or tool project and `member` names its actual
  `release-results/MEMBER.json` or
  `release-results/MEMBER.sha256-CONTENT_SHA256.json`. The bounded exact-job ZIP
  selector documented in [base binding](nest-release-base-binding.md) requires
  one unambiguous result and verifies any filename digest against the raw bytes.
  `root_pipeline` is the explicit existing config
  pipeline ID containing the direct bridge named by `bridge`. `job_name` is the
  exact downstream candidate job name, not a pattern or a guessed latest job.
- `input_pipeline` names the exact config pipeline containing that predecessor's
  unique `Freeze release inputs` job. It can be the root pipeline when the native
  graph places freezing and bridging together. It is not inferred from a recent
  successful pipeline or from the descendant's new expectations.

Pipeline IDs are positive integers, never URLs, mutable latest-success selectors
or placeholders. Obtain the root/input pipeline identities from their actual
native trigger and publication boundaries. The helper discovers the bridge's
child pipeline, exact member/input job IDs and SHA256 values of actual artifact
bytes. Its retained `binding_request` is an ordinary request accepted by
`nest-release-bind.py`; `binding` retains that helper's complete provenance.

## Acceptance and refusal

The complete binding policy and executor selector are validated alongside every
predecessor selector before any GitLab read. Invalid targets, unused producers,
incomplete/duplicate slots, mixed architectures and nonpositive/noninteger
executor IDs refuse without first acquiring otherwise valid predecessor data.
This shares the standalone binder's policy checks and changes no artifact schema.

The root config pipeline must match the selected config source and be running
or successful. Running permits downstream edges to be accepted while unrelated
independent graph jobs continue; it is not whole-pipeline success. The selected
bridge must be unique, required (`allow_failure: false`) and successful. Its
parent and downstream project, pipeline, source and ref identities are checked
against independent project/pipeline GETs. The child must be a successful native
`pipeline` source with no outgoing bridges; unexpected fan-out, including a
config/OpenBolt trigger loop, refuses this leaf-member boundary.

All current child jobs must be successful and required; a tolerated failure or
unfinished job cannot be hidden by a green child pipeline. The selected member
and input jobs must be unique, successful, unerased and independently match exact
archive/source/pipeline identities. Listing exhausts pages of one hundred rows,
with at most twenty pages per inventory, and rejects duplicate IDs, retried rows
and oversized inventories instead of silently truncating them. Superseded retries
are excluded by GitLab's default jobs/bridges listing; a changed selected retry is
caught on reacquisition rather than silently followed.

Actual predecessor input/result bytes are hashed and passed to the existing
binder, which checks the full member result, executor receipt, release/source
closure and compatible base edges. All native selections and hashes are acquired
again after binding. A changed bridge, child, job inventory, archive identity or
artifact refuses the result. A parent transitioning from running to successful
also requires a fresh invocation; refusal never retries or rebuilds anything.
These are bounded observations, not a server-side snapshot or artifact signature.

## Verification, remaining integration and rollback

Offline fake-GitLab tests cover discovery into real binder validation, paginated
inventories, hidden/tolerated failures, ambiguous/retried/moved resources, trigger
loops, changed artifact bytes, incompatible results, static error output and the
actual CLI's durable file readback. Existing native nonpublishing status fixtures
can verify real pipeline/listing reads and refusal of fixture-only results. They
cannot supply an OS member result, and are never called candidate publication.

The adapter uses ordinary glab authentication. Production CI job-token API access
and permissions remain unproven; do not inject a user token into a job as a shortcut.
Automatic graph generation, per-edge input freezing, accepted old-executor to
OpenBolt to new-executor bootstrap, aggregate result assembly, capacity/ABI/resource
admission, promotion/rollback and host lifecycle integration remain required. No
real build is launched merely to manufacture an artifact for discovery testing.

Rollback stops invoking this optional helper and uses retained exact binding
requests or the existing explicit immutable-input path. Previous expectations,
results, image digests and rollback artifacts are unchanged. Disruptive reset,
reboot, cleanup and release-alias promotion remain separately gated.
