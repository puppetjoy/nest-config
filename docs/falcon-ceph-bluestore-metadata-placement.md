# Falcon Ceph BlueStore metadata placement

Falcon's Rook/Ceph HDD OSDs keep their `data` PVCs on
`nest-crypt-block`, backed by the physical HDD `nest` pool. Their BlueStore
metadata PVCs use `data-crypt-block`, backed by Falcon's physical mirrored
Samsung 870 EVO SSD `data` pool. This avoids recursive ZVOL-as-SLOG storage
while preserving synchronous-write semantics on both pools.

Rook's `metadata` volume claim is the combined fast device for BlueStore
`block.db` and `block.wal`. Ceph implicitly places WAL on the DB device when
there is no separate `wal` claim, so a third device adds no benefit here.

## Sizing and capacity

- Production: 32 GiB of metadata for each 1 TiB HDD OSD (3.125%).
- Test: 8 GiB of metadata for each 300 GiB HDD OSD (2.67%).
- Maximum allocation across both clusters: 120 GiB.

Ceph recommends at least 2.5% when WAL and DB are offloaded to a faster
device. These sizes satisfy that floor. At design time the Falcon `data` pool
was 71% allocated with about 188 GiB available to
`data/crypt/kubernetes`. Full allocation of all six metadata volumes would
leave about 68 GiB available and put the pool near 84% allocation. Recheck
this capacity immediately before deployment; do not proceed if the pool no
longer has that headroom.

## Existing OSD migration

Changing `volumeClaimTemplates` does not move BlueStore metadata for an
existing OSD. OSDs 0, 1, and 2 were created with only a `data` PVC, and live
metadata inspection showed no external `bluefs_db_dev_node` or
`bluefs_wal_dev_node`. Each OSD must therefore be destroyed and recreated to
adopt the new metadata device.

Migration is a reviewed storage-maintenance operation, separate from applying
the source manifest:

1. Require both Ceph clusters to be `HEALTH_OK`, all PGs `active+clean`, no
   recovery or backfill, and current backup plus restore evidence.
2. Record the OSD-to-data-PVC mapping and verify the new metadata PVC is bound
   to Falcon through `data-crypt-block`.
3. Exercise the test cluster first. Use Rook's PVC-backed OSD removal flow for
   exactly one OSD, wait until Ceph reports it safe to destroy, then purge and
   recreate that OSD with its data and metadata claims.
4. Verify the recreated OSD is `up` and `in`, its PGs return to
   `active+clean`, and `ceph osd metadata` reports external DB/WAL device
   paths before touching the next OSD.
5. Repeat one OSD at a time for the remaining test OSDs, then repeat the same
   sequence for production. Never remove two failure-domain OSDs together.
6. After production converges, verify RGW, `registry.eyrie` manifest pulls,
   fresh Honcho and representative non-Honcho backups and artifacts, CNPG
   continuous archiving, and the documented restore path.

Do not treat an ordinary chart apply as migration completion, and do not
delete old data PVCs until Ceph explicitly reports the named OSD safe to
destroy. The live purge/recreate commands and PVC identities must be captured
for implementation review immediately before execution.

## Rollback

Before any OSD is purged, roll back the source values and remove any unused
metadata PVCs; existing data-only OSDs remain unchanged. Once an OSD has been
purged, the operation is not reversible in place. Finish recreating that one
OSD and return the cluster to `active+clean` before deciding whether to stop.

If the fast-device design itself must be rolled back after an OSD has been
recreated, restore the prior source values and reprovision that OSD as
data-only using the same one-at-a-time, safe-to-destroy gate. Never restore
the removed cross-pool ZVOL SLOG topology and never set `sync=disabled` on
`nest`, `data`, or their Ceph-backing datasets.
