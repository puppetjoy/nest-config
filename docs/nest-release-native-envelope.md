# Native multi-architecture release envelope

`scripts/nest-release-envelope.py` acquires a complete selected program through
the existing native discovery, predecessor and per-architecture assembly
contracts. Each architecture retains its original manifest and independently
queried executor receipt. It never presents one amd64 image as an ARM/RISC-V
executor, and never relabels old-executor/OpenBolt/new-executor bootstrap phases
as a single same-source release.

This is the final aggregation boundary, not automatic graph execution, resource
admission, promotion or host rollout. It performs authenticated GitLab GETs only;
no build, trigger, retry, tag update, host operation or private-root read exists.

## Invocation and request

From the config checkout with existing authenticated `glab`:

```sh
python3 scripts/nest-release-envelope.py --envelope /absolute/envelope-request.json
python3 scripts/nest-release-envelope.py --envelope /absolute/envelope-request.json \
  --output-dir /existing/canonical/artifact/directory
```

The schema-1 request fields are exactly:

- `schema`: integer 1; `kind`: `nest_release_envelope_request`.
- `release` and `sources`: one selected release token and complete existing
  immutable source closure, identical in every architecture. Differing config
  revisions cannot be relabelled into this envelope.
- `consumers`: the existing complete consumer-decision array, with global member
  IDs. Every selected output and known tool consumer must be classified, including
  excluded/deferred legacy consumers. `reuse` still requires actual accepted
  original production; an empty deferred consumer is not an updated artifact.
- `assemblies`: a nonempty map keyed by the existing executor CPU group names
  `haswell`, `cortex-a53`, `sifive-u74`. Each value is the complete schema-1
  `nest_release_assembly` request documented in
  [native assembly](nest-release-native-assembly.md). Include exactly the
  independently selected architecture groups, not invented successful rows for
  architectures outside the scope. The combined matrix is limited to 128 members.

Member IDs, complete CPU/platform/variant/host selections, Stage 3 host identities
and private identity references must be unique across the entire program. Each
architecture uses a different exact executor image and successful architecture
job. Haswell/Zen5, supported ARM CPUs and SiFive/T-Head follow the existing binder
mapping; metadata alone is not ISA or ABI proof.

Every architecture includes the same consumer-project inventory as the global
selection. A consumer with local members uses the global decision. A globally
selected consumer with no members in that architecture is locally `defer`; a
consumer with no members anywhere preserves the global `defer`/`retire` decision.
Local and global reasons remain retained ordinary input data. Review them for
sanitization before sharing; the schema is not a secret scrubber.

## Acquisition and publication

The entire selection is validated before external reads, including every
architecture's complete producer selector inventory, exact member/project
association, positive integer pipeline IDs and nonempty bridge/job names. A
malformed later architecture cannot initiate acquisition for an earlier one.
The same static admission applies to standalone assembly and predecessor
discovery. This changes no artifact schema or accepted resource identity.
The existing assembler
checks exact required bridges, downstream sources, successful unerased jobs,
original frozen input/result bytes and independently selected executor receipt
bytes. Global producer identities and published host-root GUIDs cannot repeat
across architectures. Normal/debug pairs, platform compatibility declarations,
private identity references and versioned host roots remain unchanged.

After acquisition of all architectures, the helper reacquires each through the
same assembler and requires identical manifests, artifact selections and native
observations. A prior architecture changing while a later one is read refuses
rather than mixing observations. This is bounded observation, not a server-side
transaction or signature. It does not poll/retry builds; a pipeline moving from
running to success during acquisition may require a fresh read-only invocation.

Default mode prints only counts and an envelope digest. `--output-dir` retains a
single content-addressed, no-clobber envelope using the existing fsync and exact
readback publisher. The file contains the complete selected source/consumer
policy, request digest and original assembly packages, not just references to
volatile local input files. It remains readable after the request file is removed.
The existing four MiB JSON read limit applies to the retained envelope as well;
an oversized result is refused before publication. Existing artifacts are never
replaced. `path` and `readback_verified` describe actual optional local retention,
not an alias promotion or deployment receipt. Exit 0 means acquisition and any
requested publication/readback succeeded, 1 is static operational refusal, and
2 is invalid CLI arguments. Native errors/private diagnostics are not echoed.

## Tests, limitations and rollback

Ordinary source CI runs the offline envelope tests alongside assembly, discovery,
binder and manifest tests. Real validation is exercised with fake GitLab data
for all three executors, Stage 0/1 normal/debug pairs, Stage 2, distinct Stage 3
roots/private references and tools. Faults include missing global members,
contradictory decisions, different source closure, shared/wrong executors,
erased/failed resources, duplicate host/root identity and cross-architecture
acquisition changes. The real CLI is exercised with a fake `glab` and reopened
content-addressed output. These are fixtures, not real candidate releases.

Automatic native graph generation and per-edge input freezing, the distinct
accepted old-executor -> OpenBolt -> new-executor bootstrap, production job-token
permissions, actual candidate acquisition, resource/ISA/ABI admission, explicit
alias compare-and-swap promotion/rollback and host lifecycle integration remain
open. In particular this envelope cannot combine outputs from different config
source closures to hide the bootstrap boundary. No candidate OS/tool build is
launched merely to manufacture artifact evidence. The live disruptive canary is
separately owner-gated; source tests and merged tooling are not reboot acceptance.

Rollback stops invoking this optional aggregation helper. Retain all prior exact
manifests, source/input/result artifacts and rollback handles. No release alias,
backup, boot selection or transaction state changes when this helper is removed.
