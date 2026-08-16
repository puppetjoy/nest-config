# Falcon ZVOL-backed SLOG incident and recovery

## Scope and content safety

This runbook records topology, health, and control-plane evidence only. It does
not contain backup payloads, credentials, object names, or database contents.

## Incident signature

The cluster-wide backup failures were downstream of a Falcon ZFS deadlock, not
a 30-minute backup sizing problem:

- `data` and `nest` each used a ZVOL from the separate `falcon` pool as a log
  vdev: `/dev/zvol/falcon/slog/data-part1` and
  `/dev/zvol/falcon/slog/nest-part1`.
- Both pools stopped completing transaction groups while `falcon` continued to
  complete transaction groups. ZFS deadman events identify synchronous writes
  stalled at those two ZVOL log vdevs.
- Falcon accumulated more than 140 blocked tasks, including ZFS transaction
  group threads, PostgreSQL WAL writers, NFS workers, and Ceph OSD I/O.
- All three HDD Ceph OSDs on Falcon then became unavailable. CephFS and RGW
  degraded, so backup writes to `/nest/backup` stopped and registry operations
  stalled. GitLab PostgreSQL WAL writes on the local `data` pool also stopped,
  which made GitLab registry token requests return HTTP 503.
- The NVMe backing the `falcon` pool reported no media or integrity errors.
  This matches the known OpenZFS cross-pool ZVOL-as-SLOG deadlock documented in
  [OpenZFS issue 1131](https://github.com/openzfs/zfs/issues/1131) and reproduced
  again in [issue 6065](https://github.com/openzfs/zfs/issues/6065).

The first affected daemon and WAL evidence converges at approximately 02:19 on
2026-08-14. Last successful scheduled backups completed before that window;
subsequent jobs either exceeded their active deadline or could not start while
the storage and registry paths remained blocked.

## SLOG performance requirement

The SLOGs were intentional: they kept synchronous writes off the pools' normal
latency path. They cannot remain attached, however, because a SLOG implemented
as a ZVOL from another Linux OpenZFS pool is the topology that deadlocked the
host. The recovery preserves `sync=standard`; it does not trade data safety for
speed by setting `sync=disabled`.

Live inventory shows that Falcon has no unused physical device or partition:
the Samsung 990 PRO is the `falcon` pool, the two Samsung 870 EVOs are the
mirrored `data` pool, and eight HDDs comprise `nest`. The repair therefore uses
the hardware already installed rather than introducing a hardware dependency.

`data` already writes to a mirrored SSD pair, so its pool-local ZIL remains on
SSDs after SLOG removal. `nest` returns to a pool-local ZIL on its HDD RAIDZ
vdevs. That can increase synchronous-write latency, but it is the only safe
in-place layout with the installed devices. The rollout explicitly measures
the resulting Ceph/NFS workload rather than assuming it is unusable. If the
measured workload needs more acceleration, the next source-managed optimization
must repurpose existing SSD capacity or place Ceph DB/WAL on existing SSD-backed
storage; it must not recreate a cross-pool ZVOL SLOG or disable sync writes.

`nest::host::falcon` installs and enables `remove-zvol-slogs.service`. It is a
required dependency of kubelet and runs after ZFS pool import. The idempotent
script removes the two unsafe log vdevs and verifies neither path remains. The
old ZVOL datasets remain preserved for forensic inspection.

## Reviewed rollout

1. Merge and deploy the Puppet change through the repository's reviewed
   inventory-backed Bolt workflow.
2. Confirm the unit is enabled as a required kubelet dependency.
3. Reboot Falcon once; the live deadlock cannot be repaired safely in place.
4. Before accepting workload recovery, verify:
   - `remove-zvol-slogs.service` completed successfully;
   - `zpool status -P data` and `zpool status -P nest` show no
     `/dev/zvol/falcon/slog/*` member;
   - all pools are online and transaction groups advance;
   - kubelet starts only after the guard succeeds;
   - Ceph returns to `HEALTH_OK` after recovery/rebalancing;
   - GitLab webservice and both registry endpoints stop returning relevant
     HTTP 503 responses.
5. Compare synchronous Ceph/NFS latency and throughput against the pre-incident
   SLOG baseline and record the measured tradeoff. Keep `sync=standard`.
6. Delete only incident-stale backup Jobs after the storage path is healthy,
   then trigger fresh source-managed CronJob runs. Do not patch Job templates
   or bypass `Forbid` concurrency.

## Backup and restore gates

The repair is complete only after all of these checks pass:

- a fresh Honcho backup Job succeeds and its newly timestamped artifact exists
  with non-zero size;
- one previously affected non-Honcho profile or application backup succeeds
  and produces its expected artifact;
- no incident Job remains indefinitely active, `DeadlineExceeded`,
  `ContainerCreating`, or `ImagePullBackOff`;
- Honcho and other CNPG clusters remain Ready and continuous archiving reports
  a current successful archive;
- the established content-safe Honcho restore validation succeeds against the
  fresh artifact without exposing restored records;
- a representative application/profile restore preflight can enumerate and
  validate the selected artifact without mutating production data.

## Rollback posture

Reverting the Puppet files disables the boot guard, but it does not reattach the
unsafe log devices. That is intentional: reattaching a cross-pool ZVOL as SLOG
reintroduces the proven deadlock and is not an acceptable rollback. Keep both
pools on their pool-local ZILs during an application-level rollback.

If the service fails after removing only one SLOG, inspect both pools from the
console and retry the idempotent unit. Do not bypass the unit and start kubelet
into the known cross-pool deadlock topology, and do not reattach either unsafe
ZVOL.
