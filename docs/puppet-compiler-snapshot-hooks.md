# Native compiler snapshot hooks

`files/puppet-versioned-code.rb` implements the paired native Puppetserver
code-ID and static-content command contracts. It is a source component, not a
new deployment service. It is deliberately not enabled in the OpenVox chart yet.
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
broken or escaping symlinks, control-character paths and empty trees fail.
Inventory JSON uses ASCII escaping and one trailing newline before hashing.
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

This component is deliberately not wired into the chart yet. Before enabling
it, provide an independently expected release tree, compiler-only read-only
mounts, no mutable global module paths, paired hooks, lifetime/static-content
retention and compatible existing deploy/rollout behavior. The helper is not a
generic archive copier or a new source-fetch/deployment service.

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

These requirements are still integration work, not effects of installing these
files:

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

Focused public integration-contract tests:

    pdk test unit --tests=spec/files/nest_puppet_versioned_code_spec.rb,spec/files/nest_puppet_compiler_snapshot_spec.rb,spec/files/nest_puppet_compiler_store_spec.rb
    pdk validate

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

No chart, existing deploy plan or live compiler setting changes in this source
slice. Existing human/deploy interfaces are unchanged. Keep this component
disabled until the complete snapshot publication and retention path is verified.
A later deployment rollback restores the previously accepted compiler snapshot
and its matching hooks/receipt together; never point an old ID at current r10k
content. No reset, reboot, quota change or release promotion is authorized here.
