# Kubernetes API VIP health and maintenance

The API VIP is a routing contract, separate from etcd membership. A healthy etcd
quorum does not prevent an unready API advertiser from black-holing ECMP traffic.

## Desired steady state

Eyrie's intended policy advertises `172.21.255.255/32` from Control1 and Control2. Control3 remains an
etcd voter and an API server, but is not an intended VIP advertiser. API etcd
client reads still use Control3 and Control2: advertiser selection does not
silently change the measured slow-voter endpoint policy.

`nest::kubernetes::generate_kube_vip_manifest` uses kube-vip v1.2.4's native BGP
health checking. Each advertiser checks its own strict HTTPS `/readyz`, including
etcd readiness, with the Kubernetes CA mounted read-only. It does not check the
VIP, use an insecure TLS bypass, or substitute the lighter static-Pod probe.

The integration helper also binds the local readiness hostname to loopback in
the static Pod's `hostAliases`, retaining the generated `kubernetes` alias.
This preserves the hostname used for certificate verification while removing
DNS from the bootstrap path. An otherwise healthy API must not lose its VIP
because its own short node name is sent to a public resolver while cluster
DNS is still starting. No external resolver or cluster service is required for
this node-local check.

The check period is ten seconds, timeout three seconds and withdrawal threshold
two consecutive failures. Startup suppresses advertisement until the first
successful check; recovery re-announces automatically. Detection is not instant,
and transient client failures during detection remain possible. This is not a
promise of zero-loss failover or a replacement for planned withdrawal. A shared
backend readiness failure can withdraw every gated advertiser: do not roll the
last stable management advertiser onto this policy until backend health and
the resulting route behavior are independently certified. Preserve a tested
rollback configuration throughout that transition.

Upstream manifest generation emits the CA environment setting but omits its
volume. The small manifest integration helper supplies that public-file mount
and preserves portable YAML, including the leading colon in `:2112`. Publication
is atomic through hidden temporary files. Replaced manifests are backed up
outside kubelet's watched directory under `/root/kubernetes-manifest-backups`.

## Client route ownership

BIRD owns the client kernel routes in table 100. On networkd-managed hosts,
`ManageForeignRoutes=no` keeps networkd from deleting routes owned by BIRD or
the CNI. `KeepConfiguration=static` alone does not preserve `proto bird` routes.

The Stage 3 incident exposed a separate client-side failure, not simultaneous
withdrawal by both advertisers. At 2026-10-19 21:41:05 UTC, Owl's networkd log
recorded removal of the BIRD multipath VIP route while configuring `podman1`.
Synchronized samples showed an empty kernel route, unchanged BIRD RIB entries
and Established BGP sessions. Networkd also removed a CNI blackhole route.
BIRD restored the VIP route at 21:41:31 UTC. This explains that observed route
loss, not every earlier API/backend deadline.

[Systemd's route cleanup implementation](https://github.com/systemd/systemd/blob/v262/src/network/networkd-route.c)
documents that foreign IPv4 multipath and unreachable routes cannot be assigned
to one interface during cleanup; the supported ownership setting is
`ManageForeignRoutes=no`. Global networkd configuration requires a daemon
restart, not merely `networkctl reload`. The narrowly tagged
`bird_route_ownership` Puppet resources change this setting and notify networkd.
Apply on one host only after verifying its network configuration and recovery
path; independently verify SSH, addresses, DNS, routes and networkd afterward.
Do not restart control-plane networking in parallel or touch excluded consoles.

After application, observe normal container bridge creation with simultaneous
kernel-route, BIRD-RIB, API and networkd-log checks. Do not intentionally remove
a production route to manufacture an acceptance test. A quiet interval without
bridge creation does not exercise this regression.

## Planned maintenance

Replace or withdraw one existing advertiser at a time. The Bolt plan refuses
bulk replacement/withdrawal and requires an explicit different survivor plus
complete `maintenance` inputs described below. Before publication/removal it
now calls `nest::kubernetes::check_control_plane_maintenance`: actual external
client kernel path and TLS, observed API-client-bound advancing quorum, relevant
etcd backing pools, Ceph availability and declared physical independence. The
former target-side BIRD RIB/direct-curl checks are not an alternative admission path.

Use an independently reviewed private parameter file, not the old survivor-only
command. It must include the complete maintenance input; these examples do not
authorize a production change:

    bolt plan run nest::kubernetes::generate_kube_vip_manifest --params @/absolute/path/vip-maintenance.json

For intentional withdrawal, the same document sets `advertise=false` and the
exact single target. Missing admission fields refuse before manifest mutation.

After each change, wait for actual static-Pod turnover if content changed,
BGP session convergence and the client's kernel next-hop set. An old mirror Pod
may briefly report Ready while its replacement is not yet available. Verify
strict direct readiness and VIP readiness, then inspect fresh logs. Do not infer
service continuity merely from a successful manifest write.

Never remove or maintain the sole surviving advertiser. Before host reset,
reboot or heavy maintenance, prove another healthy advertising path, withdraw
the target and verify client routing no longer selects it. Keep restoration
artifacts outside the watched manifest directory. Do not restore an unhealthy
member just to increase the advertiser count.

## Bounded etcd progress check

`nest::kubernetes::check_etcd` exposes the existing maintenance gate without
running reconciliation. It uses ordinary inventory-backed Bolt escalation on
one explicitly selected voting member. For example:

```sh
bolt plan run nest::kubernetes::check_etcd target=control1 'etcd_servers=["https://172.22.4.8:2379","https://172.22.4.9:2379"]'
```

`etcd_member_names` defaults to the three existing controllers; a different
complete unique odd voting topology of three through seven members must be
explicit. The observer must be in that set. `etcd_servers` is a nonempty unique
TLS seed list, not a membership waiver: native `--cluster` discovery and the
validator must still cover every expected voter exactly once. The supported
endpoint port is 2379. No credential bytes appear in parameters or output.

The guard performs two native endpoint health, status and membership acquisitions,
with `sample_seconds` from one through five (default two) between them. Each
kubectl request has a ten-second request timeout; etcdctl uses a three-second
dial and five-second command timeout. An outer fifteen-second deadline, with
a two-second termination grace, also bounds each command's streaming transport.
No retry, synthetic application write,
snapshot, checksum scan, compaction, defrag or service operation is generated.
Temporary mode-private sample files are removed on normal success/failure.
Transport loss or process termination can leave private scratch, not a receipt
or permission to repeat a disruptive operation.

Both samples require exact unique positive member IDs, one cluster and leader,
consistent raft term, no reported errors, valid committed/applied indexes and
bounded applied-index lag (`max_lag`, zero through 1000, default 1000).
Every member's applied index must advance while member/name/endpoint bindings,
cluster ID, leader and term remain unchanged. Reordered rows are harmless.
A quiet cluster with no observed advancement, a leader turnover or a transient
disagreement refuses conservatively; it is not proof of data loss or permission
to repair/restart etcd. Diagnose only the failed boundary rather than repeating
the fleet update. The old positional validator interface remains a single
snapshot check and never claims advancement.

The returned `nest_etcd_check` contains the sanitized quorum result with decimal
string cluster/member/leader IDs and per-member progress, but always an empty
`reboot_eligible` and `acceptance_recorded=false`. Validator bytes come from the
selected Bolt module, not an assumed installed helper revision. Existing API-only
reconciliation invokes this same gate before mutation and after readiness;
it does not broaden its certificate/etcd mutation authority.

This is only the quorum portion of maintenance admission. It does not verify
the kube-apiserver's actual configured client endpoint list, survivor VIP kernel
route, USB/power coupling, relevant Ceph/storage health, recovery route, prepared
transaction or release/disruption authorization. Those gates remain required
before a real host outage; successful quorum sampling alone cannot enable host
reboot. No fault injection or new cluster operation is authorized by this example.

### Bind quorum sampling to an observed API client's configuration

`nest::kubernetes::check_apiserver_etcd` composes the same progress guard with
read-only discovery on one explicitly selected API/voting member:

```sh
bolt plan run nest::kubernetes::check_apiserver_etcd target=control1
```

It reads the selected module's endpoint projector, the member's static API
manifest and the native `kube-system/kube-apiserver-MEMBER` mirror Pod. Both
must contain the same unique explicit TLS `--etcd-servers` list. The mirror
must belong to the selected node and have one ready, running API container
with a native runtime identity. Unsupported argument forms, unavailable API
reads, malformed inputs, missing status and configuration disagreements refuse;
none are treated as zero failures. The observed list, not a guessed seed list,
is passed to `check_etcd`. Optional `expected_servers` requires an exact set
match with an independently reviewed endpoint policy before quorum acquisition.
Reordered lists do not change identity. The separate `check_etcd` interface
retains explicit seed-list semantics for existing reconciliation callers.

The API observation is repeated after quorum sampling and must retain identical
endpoint, mirror, Pod and container identities. Each native API read has the
same request and outer streaming deadlines as the quorum acquisition. Private
temporary Pod data is removed on ordinary success/failure; only sanitized
endpoint/runtime identities are returned. Parser errors never echo source YAML,
Pod contents or unrelated arguments. No certificate material is returned.

This observes kubelet's reported runtime and current selected manifest, not
an independent process-memory attestation. It is bounded point-in-time evidence
for that member only, not all API clients or ongoing availability. Neither
plan changes endpoints, runs reconciliation, restarts a component, repairs
etcd, records update acceptance or makes a host reboot eligible. Survivor TLS,
actual client kernel route, storage and physical coupling, transaction/release
binding and separately authorized maintenance remain required.

### Observe a survivor from an external client's actual kernel path

`nest::kubernetes::check_api_survivor` is a read-only composition of the existing
strict VIP readiness policy and the API-client-bound quorum check. For example:

```sh
bolt plan run nest::kubernetes::check_api_survivor target=control2 survivor=control1 client=owl 'advertisers={"control1":"172.22.4.7","control2":"172.22.4.8"}'
```

Each selector must resolve to exactly one inventory identity. The target and
survivor must be different existing controllers, and the client must be external
to the controller set. The explicit advertiser map binds intended controller
names to unique IPv4 next hops; it is policy, not discovered approval. The
survivor must be present, even when the target is a nonadvertising controller.

The survivor's static VIP manifest and ready mirror Pod must agree on image,
VIP, BGP router ID, strict local readiness URL and read-only Kubernetes CA mount.
The client must have the exact BIRD route in kernel table 100 and a native route
lookup through that table and a matching usable gateway/device. The survivor's
own address must be a next hop; every next hop must be declared. A healthy BIRD
RIB alone, a reflected next hop, an empty kernel route, dead/linkdown routes,
local/default routing or a lookup through another table refuses. This interface
currently supports IPv4 direct gateway and ECMP routes, not nexthop-object IDs.

From that same client, bounded curl requests verify the CA and the same API TLS
name independently against the direct survivor and VIP. Curl configuration and
proxy inheritance are disabled; no credentials, redirects, insecure bypass or
retry are used. The survivor's actual API endpoint/quorum check then runs.
Client TLS checks repeat afterward, followed by kernel and VIP runtime checks.
Next-hop ordering and incidental ECMP flow selection may change; the usable
next-hop set, VIP Pod/container and mirror identities must not. All temporary
observations are mode-private and removed on normal success/failure. Results
contain sanitized identities only, with `reboot_eligible=[]` and
`acceptance_recorded=false`.

This observer alone remains bounded evidence, not withdrawal, route persistence
through a bridge change, ongoing availability or outage authority. The existing
mutation/preparation paths now consume it through the integrated preflight below.
No production route or bridge is changed for the observation.

### Integrated maintenance preflight

`nest::kubernetes::check_control_plane_maintenance` is the read-only composition
called by existing VIP replacement/withdrawal, control-plane reconciliation and
transactional controller preparation. It accepts `target`, `survivor`, `client`,
`advertisers`, `physical_domains`, `ceph_fsid`, optional `vip` and optional
`expected_servers`. The first four identity/advertiser inputs retain the observer
semantics above. `ceph_fsid` is the independently reviewed exact Ceph UUID, not a
newly generated identifier or permission to accept whichever cluster responds.
API/VIP-only operations may explicitly pass null when Ceph availability is not
a dependency of their scope (including initial bootstrap before Ceph exists).
The result then records `not_requested_api_only`, not a successful Ceph check.
Controller root preparation always requires a valid non-null FSID and cannot
use this API-only option. No operation on a Ceph/storage host is implemented here.

`physical_domains` maps inventory names to nonempty unique arrays of physical,
power and USB dependency tokens. Every controller, every member of the resolved
`eyrie-storage` group and the external client must have an explicit entry. Each
token uses lowercase alphanumeric, underscore, dot or hyphen, at most 128
characters. Do not supply hypothetical singleton memberships to make a real
check pass. Include transitively shared physical dependencies, not service/quorum
roles. The target must share no declared physical token with any remaining
voter, storage member or client. Shared memberships among protected hosts are
allowed. The known Kestrel/Control1/Control2/Storage2 USB topology must not be
erased; a conflicting scope refuses rather than inventing independence. Such a
refusal is conservative, not proof of an electrical root cause or permission to
reset the coupled device. Directed/partial impact exceptions are not supported.

Physical memberships are reviewed policy, not discovered electrical evidence.
The output explicitly says `physical_independence=declared_policy_only`; it
cannot verify omitted or misdeclared dependencies. Inventory resolution uses
ordinary Bolt and may contact PuppetDB; there is no implicit root SSH fallback.

Before and after the actual survivor observation, bounded native reads inspect
each voter's `/var/lib/etcd` backing ZFS dataset, its pool GUID, ONLINE status and
native `zpool status -x` health. Non-ZFS, missing/ambiguous mount evidence,
permanent pool errors, timeout or changed dataset/pool identity refuse. An
unrelated retired pool is not automatically made an etcd availability dependency.
No filesystem snapshot, scrub, checksum scan, replication or capacity rehearsal
is run. This is pool availability, not copy/promotion capacity admission.

The same external client reads native Ceph status through the existing
`rook-ceph-tools` deployment with bounded kubectl/exec timeouts. The selected
FSID must agree; all monitors must be in quorum, all OSDs up/in, every PG active
and clean (ordinary/deep scrubbing is allowed), no remapped PGs, and manager/MDS
availability must be known. Unsupported or missing native fields refuse. Ceph
warnings `OSD_NEARFULL`, `POOL_NEARFULL`, `RECENT_CRASH` and
`RECENT_MGR_MODULE_CRASH` are retained as warning names, not cleared or treated
as current availability failures. Other checks, including slow operations,
degraded/full states and unknown warnings, refuse conservatively. This narrow
warning classification does not admit a new write workload or waive release
capacity policy. Sanitized cluster/quorum/OSD/PG/warning identities must remain
unchanged over the observation. No raw daemon metadata or credentials are emitted.

VIP `maintenance` has exactly `client`, `advertisers`, `physical_domains` and
`ceph_fsid`; its target, survivor and VIP are bound by the existing plan's own
parameters. Reconciliation `maintenance` additionally requires `survivor`; its
target is bound by the one resolved member. Reconciliation rechecks the same
preflight after lock acquisition before uploading configuration; failure releases
the lock without starting the cluster mutation. Existing API-only kubeadm/tool,
backup, independent rollback and postcheck semantics are preserved. Fresh VIP
manifest creation with no existing advertiser retains its bootstrap path; it is
not a way to replace or withdraw an existing manifest without admission.

All these paths fail closed if a deployed caller still supplies only the old
`survivor` input. In particular, `nest::kubernetes::init` forwards the required
`vip_maintenance` inputs for excluded-advertiser withdrawal and rejects their
absence before starting/stopping any service. `nest::eyrie::build` requires and
forwards that same parameter before its first step. Fresh bootstrap still needs
an independently configured external client with the correct cluster CA and
route. Do not bootstrap or rebuild a cluster to exercise the guard.

Bootstrap creates and waits for joining VIP advertisers before serial final API
reconciliation, selecting a different member from the intended advertiser set
and forwarding the same reviewed maintenance input. It must not try to certify
a survivor whose manifest has not yet been generated. `upgrade_node` requires
the exact per-controller `maintenance` map before repository synchronization or
package installation and forwards each entry to reconciliation. Its worker-only
path remains unchanged; no implicit supervisor or root-SSH repair is added.

Successful output contains the exact target, API observation, sanitized storage
identities and warning names. `reboot_eligible=[]` and
`acceptance_recorded=false` remain mandatory. This is not a prepared-transaction
proof, release/window authorization, target withdrawal/postwithdrawal route
proof, live host/storage disruption permission or ongoing service guarantee.
The first real reset/reboot and disruptive failover exercises remain separately
owner-gated. Do not use a successful standalone preflight as a reusable lease.

## Heavy control-plane work

No raw snapshot replication or capacity rehearsal may run unbounded on a live
control-plane member. Low-priority `nice`/`ionice` alone does not constrain ZFS
kernel memory or I/O pressure. The interrupted Control3 seed is not authorized
for automatic replay or resume by this routing repair.

Before any future capacity experiment, require an explicit bounded transfer
rate, bounded CPU/userspace memory, elapsed-time limit, exact operation receipts,
and concurrent independent API/etcd/route observations with stop criteria. Verify
those controls on the actual host; do not claim a cgroup memory cap also bounds
ZFS kernel allocation. Preserve resumable targets and snapshots after an
interruption. This document does not supply or certify a replacement transfer
implementation: that pressure-safety gate remains separate from VIP repair.

## Acceptance

Etcd client routing canaries use `nest::kubernetes::reconcile_control_plane`, one
member at a time. That plan renders only the API static manifest through
`kubeadm init phase control-plane apiserver`, using the same config and patches
for dry-run and publication. Do not substitute `kubeadm upgrade node phase
control-plane`: that broader phase can restart etcd and renew Kubernetes
certificates even when only API read endpoints were intended to change.

The installed kubeadm tool must also support the running cluster version. A
Stage 3 root can contain a newer kubeadm than its still-running static Pods;
API-only reconciliation must not turn that mismatch into an implicit cluster
upgrade. The optional `kubeadm_version` argument selects an exact Gentoo binary
package only after checking that it matches the live kubeadm ConfigMap's
`kubernetesVersion`. The previous executable and version are preserved outside
the watched directory. Tool selection is refused with `upgrade_components=true`.
An unavailable binary package fails closed rather than starting a source build.
Omitting the argument leaves the installed tool unchanged.

For a live v1.34.2 cluster with an incompatible newer host tool, for example:

    bolt plan run nest::kubernetes::reconcile_control_plane targets=control2 'etcd_servers=["https://172.22.4.9:2379","https://172.22.4.8:2379"]' kubeadm_version=1.34.2

Afterward, independently verify the installed tool version, actual API
container turnover when required, unchanged etcd containers and public
certificates, direct readiness, quorum and the preserved rollback executable.

The optional host-level `nest::service::kubernetes::apiserver_go_memory_limit`
manages a kubeadm patch setting the API process's `GOMEMLIMIT`. It accepts
positive integer MiB or GiB values; the default is absent. Control2 retains its
qualified `1GiB` budget; Control3 selects `1GiB` for its own guarded canary.
Puppet manages the input file without notifying kubelet or regenerating
static manifests. Use `kubernetes_api_memory` for a narrowly tagged catalog
application, then separately reconcile the API only if its desired input changed.

The Control2 decision retains a stable canary, not a fleet-wide causal claim:
the mature thirty-minute natural-workload window had no sampled strict or
authenticated API failures, unchanged containers, six subsecond etcd compactions
and API RSS between 837705728 and 981229568 bytes. The Go heap cycled through
multiple collections instead of simply remaining small immediately after startup.
Restart effects and workload differences still confound comparison with other
members. `GOMEMLIMIT` is a soft Go-runtime budget, not a hard RSS cap or proof
that ZFS copy/reset pressure is safe. Do not apply this setting to the other
controllers without their own evidence. If the budget harms latency or CPU,
remove the host selection and the exact patch, then restore the preserved API
manifest through a guarded single-member rollback; restoring the manifest alone
would let the next kubeadm reconciliation reintroduce the budget.

Control3's separate canary addresses measured post-defrag pressure, not an
assumed fleet-wide benefit. Its database shrank from about 200 MB to 65 MB, but
a later natural-workload interval still recorded an etcd major-fault step of
5592 and a 3.8-second compaction. Its API RSS was about 1.2 GB while available
host memory fell below 750 MB. This supports testing a bounded Go heap, not a
claim that memory pressure is the sole cause. Control2 serves a different
request mix, so its lower RSS is not a matched causal comparison. Require
Control3's actual heap/GC, CPU, fault, API error-counter, object-read and
compaction evidence before accepting the canary or attempting payload work.
Keep the API-only rollback manifest and remove the host input too if rejected.

Require a sustained log-correlated interval with intended advertisers healthy,
correct external next hops, successful strict API and etcd proposal checks,
advancing synchronized members, no unplanned leader changes or proposal failures,
controllers retaining leases, and healthy critical workloads. Report residual
slow-apply warnings separately from API failures. Any fresh API timeout, missing
route or readiness failure must be diagnosed before control/storage rollout
continues. A canary proves only its exercised behavior, not the full fleet's
Stage 3 acceptance.
