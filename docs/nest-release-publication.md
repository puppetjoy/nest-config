# Release publication and selected Stage 3 placement

These interfaces finish the practical publication source boundary. They extend
existing manifests, the stopped-root publisher and the Stage 3 adapter. They do
not authorize an OS build, promotion, host reset/reboot or storage cleanup.
Ordinary source delivery does not select either operation.

## Explicit image promotion and rollback

`scripts/nest-release-promote.py` takes four required file arguments:

- `--manifest`: the complete checked candidate release manifest.
- `--previous`: the complete retained manifest currently selected.
- `--plan`: an explicit alias mapping, described below.
- `--pointer`: an existing canonical absolute JSON file containing the previous
  manifest. Initialize this once from the independently verified current release;
  absence is a refusal, not permission to invent a rollback release.

The default is read-only: no lock, output file, tag write or pointer replacement.
It checks all candidate and rollback image manifests through native `skopeo
inspect --raw`, including exact SHA256 bytes, and compares every alias with the
selected old digest. For both manifests, Stage 3 roots must pass the existing
local native GUID, seal and content checker. Run on the publication host with the
required read permissions and mount view, not an arbitrary NFS-only CI container.
No hardware/ISA/ABI or full-layer integrity claim follows from manifest reads.

The plan has exactly `schema: 1`, `kind: nest_release_promotion`,
`manifest_digest`, `previous_digest` and `aliases`. The digests are the canonical
manifest digests from the existing release helper, not registry timestamps.
Each alias entry has exactly `member`, `artifact`, `alias` and `old`:

- `member` identifies an existing member in both complete release manifests.
- `artifact` is `normal`, `debug` or `image`.
- `alias` is a repository-qualified tag in that artifact's exact repository.
- `old` is the immutable repository/digest reference from the previous manifest.

Every candidate image role must have an alias entry, including each normal/debug
pair. More than one explicit tag may name a role, but no tag may occur twice.
Stage 3 roots are selected by the versioned manifest, not a mutable root copy.
This interface does not synthesize multi-CPU aggregate indexes or guess members
from a CPU/tag naming convention. Publish and validate aggregate images through
the existing aggregate build path; do not pass an aggregate as one CPU member.

After exact release approval, `--apply` takes a nonblocking local pointer lock,
rechecks all inputs/resources, and retains the previous manifest and exact plan
in the pointer directory before the first tag write. It then compares each old
alias immediately before `skopeo copy --all --preserve-digests`, independently
reads back the result, and rechecks the entire alias set before atomically
replacing, fsyncing and reopening the small manifest pointer. The retained
rollback files use the existing content-addressed `release-*.json` convention.

Use the standard `skopeo` executable and its ordinary existing registry auth
configuration. Authentication stays outside manifests and command arguments;
this helper does not log native diagnostics or acquire credentials. The optional
operator utility is not automatically installed on every Nest host. If it is not
available in the selected release execution context, provision the standard tool
there before promotion; no custom registry client or authentication service is
introduced. Normal config builds do not execute this optional promotion command.

Registry tags have no server-side compare-and-swap or multi-tag transaction.
The local lock coordinates this command only. Exclusively coordinate other tag
writers during a release; the checks are bounded comparisons, not leases. A copy
failure, timeout or mismatch may leave some aliases moved, but the pointer is
not advanced. Stop and inspect actual tags. Do not rerun the original plan or
blindly reverse a possibly changed tag. Submit a deliberately reconciled mapping
for the exact observed state, retaining both manifests. No automatic retry,
rollback, image deletion or rebuild occurs.

Rollback uses the same interface: the retained previous manifest becomes
`--manifest`, the current selected manifest becomes `--previous`, and a new
explicit plan pins the currently expected old aliases and reverses the exact
artifact selection. It must pass the same readability and comparison checks.
It never rebuilds old outputs from mutable source or touches host boot selection.

## Selected local Stage 3 provisioning

The existing `files/build/finish-stage3-root.py` additionally supports
`--provision`, followed by:

- `--expectations FILE` and `--member ID`: the final frozen Stage 3 inputs.
- `--storage-guid GUID`: the independently selected existing local ZFS filesystem
  mounted at `/nest/releases`.
- `--staging-parent PATH` and `--staging-parent-guid GUID`: an independently
  selected existing local writable ZFS staging parent, disjoint from publication.
- `--receipts PATH`: an existing root-owned private directory, mode 0700,
  disjoint from staging, publication and the private identity generation.

It requires native root/ZFS permissions. The default checks only; it creates no
file, directory or dataset. The final inputs must identify a fresh Stage 3 member
and an existing distinct private identity generation. The command does not
provision identity, choose a pool, create arbitrary ancestors, increase quotas,
reserve space or claim capacity will remain available. The operator selects
storage with a reviewed real capacity budget before applying placement.

Only an authorized `--apply` creates the selected release/hosts children and the
member's empty staging child. Existing release/hosts parents are admitted only
with the exact native dataset placement, private mode and matching release
property. A prior staging child or placement record refuses, including an
interrupted attempt. No `zfs create -p`, destroy, rename or cleanup is used.
Failures leave reserved paths/datasets for inspection, not replay.

After native GUID/mount readback and the existing finisher's placement preflight,
it fsyncs and reopens the private file
`RECEIPTS/placement-RELEASE-MEMBER.json`. This is exactly the existing
`nest_stage3_local_placement` schema consumed by `bin/ci-release-build
--stage3-placement FILE` and `RELEASE_STAGE3_PLACEMENT_FILE`. It does not start a
build. Use final member inputs, including any real rebound predecessor digest;
a placement bound to an earlier graph seed will rightly refuse later.

The original finisher positional interface and `--check` remain unchanged.
Stopped-root materialization, sealing, versioned publication and independent
adapter readback still run through the existing Bolt Stage 3 plan. Provisioning
is explicit preparation on that same approved native publication host, not a
privileged-runner allocator, remote copy mechanism or automatic CI bootstrap.

## Verified boundary

The candidate adapter honors the existing Stage 3 CI variables
`CI_HOST_MAKEOPTS` and `CI_HOST_EMERGE_DEFAULT_OPTS` as the plan's `makeopts` and
`emerge_default_opts`. Empty or absent values preserve the profile defaults.
Select these ordinary build controls for the real builder's available resources;
the adapter does not reserve memory or stop other workloads to make room.
The frozen input publisher also requires the selected host's existing public CA
pin in `data/release/trust.json`. That release allowlist does not install a CA or
alter the live Puppet trust store.

### Native build with publication on another host

When the native build host and the ZFS publication host differ, use the same
Stage 3 adapter with an explicit `nest_stage3_remote_placement` record. It has
the same schema, member, expectations digest, staging, staging GUID, receipts
and publication parent GUID fields as local placement, plus:

- `target`: one configured inventory name, such as `falcon`. The Stage 3 plan
  requires the existing Joy SSH transport and uses Bolt escalation, not root SSH.
- `build_target`: the explicit inventory host running the native Podman service,
  such as `owl`, using the same Joy/Bolt transport. This is not inferred from the
  image hostname or the CI runner's container hostname. Older remote placement
  records without this field now refuse before container initialization.
- `archive`: a fresh absolute `.tar` path on an existing share visible at the
  same path on both hosts. Its existing parent must be root-owned, mode 0700,
  non-symlinked and disjoint from identity, staging, receipts and publication.
  Do not put this transport scratch in `/nest/backup`.

Select and provision the same local ZFS placement on the publication host first,
using the existing `--provision` interface above. For the adapter's remote
placement, retain those exact local fields and select the explicit target and
private shared archive; do not replace a GUID with an NFS path or weaken native
mount admission. The private identity generation must remain accessible to both
hosts through the existing share. Budget the temporary archive and both staging
and published root copies before the build. No helper chooses or expands quotas.

The CI executor needs the existing shared `/nest` view for placement and private
identity admission. Owl's existing builder runner mounts it explicitly; nested
build-container mounts alone do not make it visible to the executor. The runner
already has trusted native Podman-socket access. No host storage graph is mounted
into CI, and no root SSH transport is added.

For native Joy/Bolt operations, that trusted builder also exposes the existing
Joy agent socket read-only at `/run/nest-build-ssh-agent`. Selected jobs set
`SSH_AUTH_SOCK=/run/nest-build-ssh-agent`; other runner instances do not receive
this mount. Require a live socket and verify inventory-backed transport to both
hosts before starting a candidate. An absent or unusable agent is a refusal,
not permission to enroll a key, copy private keys or fall back to root SSH.
The read-only mount does not restrict agent signing: jobs on this builder must
already be trusted for native host access. It neither starts an agent nor changes
host authorized keys. Remove this builder volume and the selected job variable
to withdraw forwarding; do not interrupt active jobs to reconfigure the runner.

Before container initialization the plan uploads the existing sibling helpers
through Bolt to both selected hosts, checks publication-host ZFS placement, and
read-only checks the absent shared archive on the native build host. After the
build stops, `transfer-stage3-root.py export` runs on that same inventory-backed
native host and archives its stopped image layer plus exact frozen repository
volume. `podman mount` is not supported by the remote Podman client, and its local
layer paths must not be read from the CI container's different filesystem. GNU
tar's PAX/ACL/xattr/numeric-owner options preserve restore metadata inside opaque
archive bytes, including nanosecond mtimes and hardlinks. The share itself need
not support release xattrs, devices or symlinks. Host shares and build-only binds
are not payload. Stopped source and repository identities are checked again.

The root-only archive is created without clobbering, fsynced and digest-bound to
the assembled root. On the publication host, `receive` verifies that exact
archive and its retained result, reserves the existing finish intent, extracts
to the empty admitted ZFS staging dataset, compares full restored content, then
syncs and seals it. It calls the unchanged native publisher/checker. The adapter
independently reopens the final resource on that same inventory target through
`nest::build::check_stage3_root`, rather than checking an NFS view on the builder.

This is a transport option on the existing build, not a new service or general
archive import API. Only the root-owned archive made by this producer is valid.
Any failed copy, extraction, digest, mount, seal or publication leaves the
private archive, started intent and partial datasets for inspection. There is no
automatic archive deletion, retry, dataset destruction or source-container
restart. Local publication remains unchanged. Temporary helpers remain under
the selected receipts directory; they are not a system-wide installation.

The ordinary fixture job runs promotion and placement fault tests. They cover
read-only defaults, complete pairs, stale selection, failed copy/readback, exact
retained rollback and pointer behavior, selected parent GUIDs, overlap, partial
ZFS failure and no destructive retry. A separate isolated loopback registry
exercise runs the actual promotion CLI and native digest-preserving copy/readback
for synthetic scratch images, including explicit rollback and stale refusal.
It does not use real OS release images or write production registries.

Placement fixtures mock native ZFS; no user-pool dataset is allocated. Actual
selected storage permissions/capacity, complete release outputs, identity, boot
compatibility and host lifecycle acceptance remain for the separately authorized
exercise. See `nest-update-status.md` for the remaining shared lifecycle work.
