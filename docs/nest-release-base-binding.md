# Exact predecessor base binding

`scripts/nest-release-bind.py` prepares descendant expectations from actual
successful predecessor member artifacts. This is an R06/R07 building block,
not the complete release DAG or a release controller. It never predicts a
future output digest, builds, triggers pipelines, changes aliases, or operates
hosts. Ordinary source CI runs its offline regression suite.

## Invocation

From the config root with the existing authenticated `glab` installation:

```sh
python3 scripts/nest-release-bind.py --binding /absolute/binding.json
python3 scripts/nest-release-bind.py --binding /absolute/binding.json \
  --output-dir /existing/canonical/artifact/directory
```

The default performs authenticated read-only GitLab GETs and prints a bounded
summary, without writing files. The optional existing output directory receives
an ordinary schema-1 expectations JSON and a provenance package, each using
`nest-release-manifest.py`'s content-addressed, no-clobber, fsync/readback
publication. Stdout names `expectations_path` and `path`, their common
expectations digest, binding count and readback status. Exit 0 means these
checks succeeded, not that input publication or a build occurred. Operational
failures return 1 with a static diagnostic; argparse errors return 2.

The generated `expectations_path` is directly consumable by the existing
`Freeze release inputs` job as `RELEASE_EXPECTATIONS_FILE`. This still requires
selecting the exact config source and matching accepted executor. Review the
new expectations and retain the provenance package before that separate input
publication. Every rebinding changes the frozen digest when base values change;
never overwrite a predecessor's original input artifact or relabel its result
with the descendant digest. Retrying an identical binding may reuse identical
content-addressed local files; it never reruns a build. Failure between the two
file publications can leave one unaccepted local file; neither is selected by
an alias, and no successful summary is emitted until both reopen correctly.

## Binding request schema 1

The top-level fields are exactly:

- `schema`: integer 1; `kind`: `nest_release_base_binding`.
- `expectations`: a complete independently selected schema-1 expectations object
  supported by `nest-release-manifest.py`. Its bases are current known seed
  inputs, not fabricated future outputs. Selected slots are replaced only after
  exact predecessor validation; this template is not the descendant's frozen
  publication. All known tool decisions remain required. It must contain only
  members in one executor architecture group; prepare separate expectations
  for other architectures rather than reuse an amd64 executor on arm64.
- `executor_job`: exactly `pipeline` and `job`, positive integer identities of
  the selected successful config architecture build.
- `producers`: nonempty map of release-local names to exact predecessor selectors.
- `bindings`: nonempty list of exact target-slot-to-predecessor-output edges.

Each producer selector has exactly `project`, `pipeline`, `job`, `member`,
`input_pipeline`, `input_job`, `input_sha256`, and `result_sha256`. Project is an
existing supported Stage or tool project. Pipeline/job values are positive
integers, not latest-success selectors. The input job belongs to `nest/config`
and must be named `Freeze release inputs`; it supplies the predecessor's own
`release-inputs/expectations.json`. The two bare lowercase SHA256 values bind
those exact input and result bytes, respectively. Results may use the historical
`release-results/MEMBER.json` name or the hardened tool producers' name
`release-results/MEMBER.sha256-CONTENT_SHA256.json`. The result digest always
hashes the original file bytes, not reserialized JSON or the enclosing archive.
Select identities and digests from the actual successful bridge/job readbacks;
this helper does not discover or choose the latest pipeline for the caller.

Each binding has exactly `target`, `base`, `producer`, `artifact`. Target names
one selected descendant member; base names an existing `image`, `normal` or
`debug` slot; producer names one selector; artifact names that predecessor's
`image`, `normal` or `debug` result. Root artifacts are not image bases. Every
base slot of a rebound member is mandatory, exactly once. Both Stage 1 slots
must come from one predecessor result, never different independently chosen
normal/debug jobs. Unknown/unused producers, partial pairs, duplicate slots
and rebinding a `reuse` consumer refuse.

## Resource and compatibility checks

Before any external read, the binder validates the complete binding policy,
architecture selection, positive executor identities and every resolved
predecessor selector, including all numeric identities and both bare artifact
digests. Native discovery uses the same static policy admission before resolving
its first bridge. Invalid later predecessors, partial/duplicate base bindings
and malformed executor selections cannot cause earlier resource acquisition.
This is input validation, not proof that a selected native resource exists or
that an image is compatible. Successful request and result schemas are unchanged.

All reads use the fixed GitLab host through `glab api` without a shell. Paths
are limited to supported project metadata, exact jobs and the three supported
artifact namespaces and exact job ZIP downloads. No caller URL, job trace or
latest-success endpoint is fetched. Only the selected producer job archive is
downloaded, not a private identity source. Native stderr is captured, not republished.
This entrypoint uses normal existing glab authentication; it does not inject
credentials or claim that a CI job token has equivalent API permissions.

Each job must be successful, not erased, and match the exact project, source,
pipeline and artifact archive identity. Project metadata is independently read
back. Those resource facts are rechecked across acquisition; volatile runner
and user display data are not copied into the retained package. Predecessor
expectations must have the same release and complete source closure as the
new template. The result's original expectations digest, exact member,
producer source/pipeline/job, schema-2 executor receipt and ordinary output
schema must match. Missing debug outputs, stale executors, changed artifact
bytes, cross-source reuse and moved or failed producer resources refuse.

Member result acquisition inspects the selected job ZIP in memory without
extracting any paths. It requires exactly one result for the exact member;
legacy plus digest-named results, duplicate ZIP paths, multiple digests, malformed
digest suffixes, unsafe paths, links, corrupt/encrypted selected entries and
filename/content digest mismatches refuse. Even identical duplicate results
are ambiguous. Other members never substitute for the selected member. ZIP
downloads and total declared uncompressed bytes are each limited to 4 MiB,
with at most 256 entries, and selected result reads are independently bounded.
The existing full result schema, raw-byte pin and job/source checks still apply.
These bounds cover the current result-only producer archives, not arbitrary
image bundles. No archive is extracted or rewritten; old results remain valid.

The descendant executor is acquired separately from the exact successful
`Build haswell`, `Build cortex-a53` or `Build sifive-u74` job. Its own receipt
must match both that job/pipeline and the template's executor/source. CPU groups
match existing Stage consumers: Haswell/Zen5 use Haswell, ARM members use
Cortex-A53, and SiFive-U74/T-Head use SiFive-U74. The predecessor can have a
different executor image within the same accepted source closure. No aggregate
index substitutes for an exact architecture receipt.

Edges preserve the existing recipes:

- Stage 0 refresh consumes a prior Stage 0 normal output.
- Fresh Stage 1 consumes one same-CPU Stage 0 normal/debug pair. The Stage 0
  server-profile pair may seed other Stage 1 variants. Refresh consumes the
  same CPU/variant Stage 1 pair.
- Fresh Stage 2 consumes same-CPU/variant Stage 1 debug. Refresh consumes a
  Stage 2 image with the same platform and boot compatibility fields.
- Fresh Stage 3 consumes same-CPU/variant/platform Stage 2 with exact declared
  kernel, module ABI, firmware and bootloader compatibility.
- Fresh tools consume same-CPU/variant Stage 1 normal. Firefox's existing
  Zen5/workstation recipe explicitly uses Haswell/workstation as its fresh
  base. That exception does not apply to Camofox. Refresh consumes the same
  tool/CPU/variant image.

These checks verify declared relationships, not registry image existence,
actual ISA requirements, hardware boot, private identity or ABI contents. The
receipt explicitly says `image_compatibility_verification=not_performed` and
`promotion_authorized=false`. Existing trusted GitLab/runner/source publication
is still the provenance boundary; no signature or custody service is invented.
Sanitize reviewed free-text expectations before publishing local/public files:
valid JSON fields are not secret scrubbers.

## Native per-edge input publication

The existing `Freeze release inputs` CI job also accepts
`RELEASE_DISCOVERY_FILE`, a file containing the schema-1
`nest_release_base_discovery` request documented in
[native discovery](nest-release-native-discovery.md). Set `RELEASE_INPUTS=true`
and exactly one of `RELEASE_EXPECTATIONS_FILE` or `RELEASE_DISCOVERY_FILE`.
The unchanged static input path remains available for seed inputs. CI invokes
`scripts/nest-release-inputs.py --ci`; it reads file paths as data without shell
argument interpolation. Missing or simultaneous input selections refuse.

For direct invocation in the exact config CI context, use either
`--expectations /absolute/expectations.json` or
`--discovery /absolute/discovery.json`. These options and `--ci` are mutually
exclusive. The existing project, clean checkout, config SHA, pipeline/job and
public identity-trust checks apply before discovery performs any external read.
This is input publication, not a read-only invocation: it writes a fresh private
`release-inputs` directory and never replaces an existing generation.

In discovery mode, the job itself resolves the selected successful native
bridges, original predecessor inputs/results and independent executor receipt,
then freezes the actual bound bases. Failed, erased, moved, incomplete or
cross-source resources refuse before a publication directory is created.
Original predecessor artifacts are never rewritten. After successful acquisition,
the job retains the ordinary `expectations.json`, `receipt.json`, optional public
`trust.json`, and complete `discovery.json` provenance. The ordinary schema-1
receipt stays exact for existing consumers. A separate `provenance.json`
(`schema=1`, `kind=nest_release_input_provenance`) binds the input receipt bytes
with `input_receipt_sha256`; its `base_discovery` field binds the discovery
artifact SHA256 and observed edge count. All retained bytes are fsynced and
reopened; CI uploads this directory
only on success. The input job name and ordinary expectations artifact path stay
unchanged for existing consumers and the assembler.

This removes manual digest copying between discovery and input publication; it
does not start a successor pipeline. The graph must still schedule each freeze
after its actual predecessor bridge has succeeded, supply exact pipeline and
bridge selectors, and pass the resulting input job identity/digest to the next
member. Use existing authorized glab authentication. No token is supplied in the
request, and no equivalent CI job-token permissions or image/ISA/ABI admission
are inferred from resource metadata. `resource_verification=not_performed` and
`promotion_authorized=false` remain truthful in the ordinary input receipt.

Offline tests exercise the actual publisher and native discovery/binder with
fixture GitLab responses, including a separate real CLI process with fake glab.
They reopen frozen inputs/provenance after producer exit and request removal;
failed/erased/changed predecessors, dirty or wrong-source checkouts, conflicting
file selections and failed provenance readback refuse. These are not candidate
release or live artifact-access acceptance.

## Remaining integration and rollback

Actual predecessor result acquisition is covered by offline fake-GitLab and
real CLI/fake-glab fixtures. Read-only exact executor/job acceptance can run
against current managed delivery without building an OS. No actual candidate
build is launched to manufacture a predecessor artifact for this test.

Native discovery, per-edge publication and manifest/envelope assembly now have
working interfaces, but full native DAG scheduling/generation, actual production
artifact/job-token access, resource/ABI admission and explicit promotion/rollback
remain required. Config/OpenBolt
bootstrap is a distinct phase: this same-source binder deliberately rejects
cross-config-source relabeling and does not create a completion cycle between
an old executor, new OpenBolt and a new config executor. It must be integrated
through their actual separate accepted artifact boundaries. Do not call this
helper or isolated status fixtures an end-to-end release.

Rollback stops invoking the helper and retains all previously frozen inputs,
results and exact digests. Removing this optional helper and its test invocation
does not alter existing build recipes, release aliases, backup generations,
host boot selection or transaction receipts. Fleet reset/reboot/cleanup and
release-alias promotion remain outside source-test authority.
