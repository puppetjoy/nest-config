# Infrastructure test mirrors: explicit on-demand operation

Infrastructure mirrors in namespace `test` normally remain parked. Joyride TEST
is **not** this lifecycle boundary: its application, access service, delivery,
import, backup and monitoring jobs remain available, using production Ceph.
Namespaces, definitions and persistent volumes are never deleted.

Run from the current Nest config checkout with its normal Bolt inventory,
installed modules, Kubernetes context and credentials:

```sh
bolt plan run nest::eyrie::test::infrastructure action=status
bolt plan run nest::eyrie::test::infrastructure action=start
# Run the intended test, upgrade, restore or build; verify its real result.
bolt plan run nest::eyrie::test::infrastructure action=stop
```

There is no timer or autosleep controller. A deliberate test remains awake until
explicitly stopped. Never run conflicting lifecycle/deployment operations at the
same time. `status` reports the recorded lifecycle phase, not a fresh health
assessment. A failed operation is a refusal/partial transition, not success.

## Scope and ordering

Parked mirrors: GitLab (webservice, Sidekiq, Gitaly, shell, KAS, registry,
Prometheus and toolbox), its Valkey and PostgreSQL; OpenVox/Puppet server,
PuppetDB, Puppetboard and PostgreSQL; standalone test registry; test Bitwarden
and MariaDB (the current CephFS consumer); duplicate test monitoring; and test
Ceph's RGW, managers, MDS, OSDs, monitors, exporters, crash collectors and toolbox.
The PostgreSQL instances use CloudNativePG's supported hibernation annotation.

Retained: Joyride TEST and its schedules, test jump service, test ingress and
certificate services, shared CNPG and Rook operators, production storage,
production applications and production monitoring. Desktop/media services are
outside this operation.

Stop first rejects active GitLab builds/queues, infrastructure Jobs, unknown
PVC consumers, unsuspended infrastructure CronJobs, new HPA ownership and
unhealthy/unreplicated test storage. Infrastructure restore/GC CronJobs must
remain deliberately suspended; this helper never resumes them. It suspends
only the two infrastructure databases' ScheduledBackups and remembers their
original policy. Application writers stop before databases. External CephFS
sessions or RBD watchers prevent storage shutdown; Ceph's verified internal
manager session is permitted and its manager stops before the MDS. Test Ceph
must have every OSD up/in and every PG active+clean. Existing device-performance
warnings are not bypassed integrity checks.

The helper labels only the named test Ceph CRs and daemon workloads with Rook's
`ceph.rook.io/do-not-reconcile` control. It never stops the shared Rook operator.
It remembers whether `noout` was already set and removes only its own flag on
wake. Prometheus CRs are paused before their workloads stop.

Wake restores monitors/tools, OSDs, managers, MDS/RGW and monitoring; verifies
clean replicas; resumes PostgreSQL and the other databases; then starts
applications. It checks GitLab, PuppetDB and Grafana HTTPS endpoints as well as
workload readiness. Verify the particular test's data path separately; pod
Ready is not proof of application/data correctness.

The namespace-local ConfigMap `infrastructure-test-power-state` retains the
original replicas, daemon labels, monitoring pause policy, backup suspension
policy and PVC UID/PV bindings. Keep it until a successful wake. Repeating a
completed start/stop is safe; a partially completed park must be diagnosed and
resumed with `stop`, not blindly reversed with `start`. Never replace the ledger
with guessed replica counts. If a new external consumer or unsuspended schedule
is introduced, review that use before modifying the guard.

## Entry points

Test GitLab/OpenVox/registry deployments, test Ceph/monitoring deployments,
explicit Puppet code deployment to the test backend, and image-manifest
mirroring wake and check dependencies first. Rendering and initialization paths
remain non-mutating. Ordinary `nest::puppet::deploy` now defaults to production
only; request `backend=test`, `kubernetes`, `both` or `all` explicitly when the
test server is actually needed. Deployment does not automatically park mirrors
at exit, because test/upgrade work may continue after its command returns.

## Memory policy and rollback

Production HDD OSDs have a soft `osd_memory_target` of 6442450944 bytes (6 GiB).
Test HDD OSDs use 4294967296 bytes (4 GiB) and test SSD OSDs 2147483648 bytes
(2 GiB) while awake. KubeCM/Rook `cephConfig` device-class masks own these
settings. These are autotuned cache targets, **not hard cgroup limits** or total
OSD RSS guarantees. Existing overhead/residency can exceed the target. Do not
force restarts or flush caches to make a measurement look smaller. Verify the
running daemon's effective target after source convergence; persistent config
alone does not override every startup default on a newly started daemon.

To return mirrors to continuous operation, run `action=start` and leave them
awake. Revert the lifecycle entry-point/default changes only if the old behavior
is wanted. To undo a memory-policy change, revert the corresponding Hiera entry,
redeploy the existing Ceph KubeCM plan, and verify effective daemon config;
retain measured production/storage headroom rather than blindly restoring the
old node-scale fallback.

Falcon's boot configuration reserves 4096 pages per NUMA node, each 2 MiB:
`hugepagesz=2M hugepages=0:4096,1:4096`, a total of 16 GiB for Caracara. Caracara's
persistent libvirt `memory` and `currentMemory` are 16777216 KiB; its two NUMA
cells are 8388608 KiB each. Other guest configuration is unchanged. Its private
original XML remains on Falcon; do not publish it. Restoring the old 32 GiB
allocation requires the guest off and verified sufficient hugepages on both
nodes **before** restoring that XML. A reboot is not part of this lifecycle or
an authorized rollback shortcut. Boot-time command-line activation can only be
verified at a separately authorized reboot; live page accounting can be checked
without rebooting.

GitLab's bundled production Prometheus remains enabled: the shared stack does
not currently scrape GitLab's application targets, so equivalent coverage has
not been demonstrated. Park only its test duplicate with the other mirrors.
