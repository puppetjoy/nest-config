# Falcon media on Eyrie

## Durable boundary

`nest::eyrie::deploy_media` composes two KubeCM releases in lowercase `media`:

- `media-storage`: six separate retained local OpenEBS ZFS filesystem claims.
- `media`: NZBGet, Ombi, Radarr, Sonarr and Plex. GitLab Runner is excluded.

All pods stay on Falcon and tolerate its workstation taint. App deployments
use Recreate, one replica, and retain media UID/GID 1001. This is managed local
storage, not failover. The narrow `/nest` directories remain direct host mounts;
Plex has read-only movie/TV mounts. Readiness init checks require the actual
expected ZFS media datasets, readable/writable mounts and existing app state.
Do not remove these checks to bootstrap empty application databases.

The `media-crypt` config class uses `data/crypt/kubernetes`, filesystem mode,
`shared: no`, WaitForFirstConsumer, expansion and Retain. The separate
`media-downloads-crypt` class enables `shared: yes` only for the download claim;
config claims retain driver-enforced single-pod mounting in addition to
Recreate rollouts. Claims also carry Helm keep annotations. The shared
downloads claim is RWO, **not RWOP or cross-node RWX**.
Its same-node multi-pod operation must pass a simultaneous three-pod test with
the deployed OpenEBS 2.10.1 driver before any source writer is stopped.

Quotas: Plex 64 GiB, Radarr 8 GiB, Sonarr 4 GiB, Ombi 2 GiB, NZBGet config
1 GiB, downloads 100 GiB. Their total ceiling is 179 GiB. Initial discovery
found about 261 GiB available after existing reservations, about 21 GiB of app
config and 25 GiB of downloads. Refresh allocation, snapshots, reservations,
physical pool health and duplicate-copy headroom before provisioning. Do not
alter sync, reservations, pool topology or use the near-full media pool for new
download storage. Existing `/srv` data already occupies space; new quota space
must include its duplicate copy and leave rollback/write-growth headroom.

## Deployment and non-applying render

From the isolated accepted source worktree, install declared Bolt modules:

```sh
bolt module install
bolt plan run nest::eyrie::deploy_media render_to=/modules/nest/build/media-render.private.yaml
```

This renders both releases; the storage filename gains `.storage.yaml`.
The files contain registry credentials. Keep them private and ignored, never
attach or commit them. `deploy=false` is a skip, not a render.

After the normal source/CI/owner gates, storage can be provisioned without
creating any application writers:

```sh
bolt plan run nest::eyrie::deploy_media storage_only=true
```

Use bounded temporary migration pods to bind and populate the claims. Do not
activate the application release during pre-copy: an existing config file is
not a final-sync receipt. Final activation is the same plan without
`storage_only=true`, only after old services are stopped and final sync ends.
No migration/repair shell is embedded in the deploy wrapper.

## Cutover checklist

1. Refresh live identities, mounts, app versions, saved integrations, queues,
   active Plex sessions, capacity and health. Preserve exact image digests.
   The image/version initially observed for Plex is
   `1.43.5.11029-6bf8af3f0`; do not bundle an upgrade.
2. Inventory Falcon's `puppet-run.timer` and any current run. Prevent scheduled
   convergence racing cutover, then restore normal scheduling afterward.
   Applying the final Falcon catalog intentionally stops/disables only the five
   old media units. It does not delete old containers, data or the previously
   quarantined Plex container. Runner declarations and GitLab proxies remain.
3. Provision only retained storage. Inspect bound PV handles, Falcon topology,
   reclaim policy, actual ZFS quotas/reservations and inherited sync. Run the
   three-pod shared-claim test, including cross-pod create/read/rename/unlink
   as UID/GID 1001 and survival after one consumer exits.
4. Pre-copy app config separately and shared downloads once with ownership,
   ACLs/xattrs and consistent mount paths. Mount source `/srv` paths read-only
   in temporary transfer pods. No new app processes may use the destination yet.
5. Quiesce all five old writers via their inventory-backed host service path;
   verify their processes stopped. Take atomic source-dataset rollback
   snapshots including the separate downloads dataset. Keep old data and
   stopped containers for at least seven days and until successful acceptance.
   Cleanup requires a separate explicit decision; there is no automatic purge.
6. Final rsync, then database integrity checks using the appropriate application's
   SQLite implementation (Plex's own SQLite handles its schema extensions).
   Preserve WALs with their DBs. Record counts/identities without printing tokens.
7. With backed-up destination state still offline, update integrations through
   supported settings APIs when practical, or narrowly transactional offline
   settings edits. Preserve IDs, credentials and every unrelated field:

   | Consumer | Saved setting | Destination |
   | --- | --- | --- |
   | Radarr / Sonarr | NZBGet client | `nzbget.eyrie`, 443, SSL on |
   | Radarr / Sonarr | Plex notification | `plex.eyrie`, 443, SSL on |
   | Ombi | Plex / Sonarr / Radarr | corresponding `.eyrie`, 443, SSL on |
   | Ombi | ApplicationUrl | preserve `https://requests.thesatelliteoflove.net/` |
   | Sonarr | disabled historical Sabnzbd `hawk:9092` | retire only this obsolete client |

   Inventory callbacks, advertised URLs, indexers, SMTP and path mappings before
   and after. Keep `/downloads` identical in downloader/importers; do not invent
   remote path mappings. Preserve external HTTPS indexers, SMTP 587, libraries,
   requests and Plex server identity. Never report complete DB settings blobs.
8. Deploy final managed source through the normal Puppet and KubeCM plans.
   Restore normal host convergence only after retired declarations are accepted.
   Verify the old services stay stopped during repeated convergence.
9. Update and verify DNS on actual DNS consumers. Internal HTTPS uses Eyrie's
   CA and contour-workstation. The containers mount Falcon's managed CA bundle
   read-only at the normal system trust path; verify real app TLS validation,
   not merely file presence. Do not turn off certificate validation.
10. Apply the gateway's existing public Ombi proxy update. It verifies upstream
    TLS to `ombi.eyrie`, handles WebSockets, and overwrites forwarded public
    host/protocol/client headers. Other administrative apps remain internal.
    Verify redirects, callbacks and a controlled public request end to end.

## Plex GPU and client acceptance

Plex retains host networking on Falcon for native TCP 32400 and UDP discovery;
ClusterFirstWithHostNet supplies pod DNS. Test native direct playback separately
from ingress. Do not infer client usability from the web page or Ready state.

The existing generic device plugin's AMD allocation requires both renderD128
and `/dev/kfd`; that cannot advertise Falcon's Intel GPU. The additional
`squat.ai/intel-arc` resource discovers only the PCI-qualified render symlink
for `0000:05:00.0` and allocates one render device to Plex. It does not allocate
`/dev/kfd`, mount all `/dev`, rebind the GPU or modify any VM. Confirm the
symlink still resolves to DG2 A750 / i915 before rollout, and inspect actual
OCI allocation and service-identity access afterward. The pinned official
image's hardware-init script adds Plex to the allocated device's group.

The exact image lacks a system iHD driver, and Plex's driver cache was empty
before it had GPU access. Its bundled libva/libigdgmm use Plex's musl runtime;
do not install a random glibc iHD package and assume ABI compatibility. Check
Plex's own downloaded driver/cache and startup/transcoder logs in the actual
GPU-allocated image. Source-manage any demonstrated missing compatible
prerequisite, retaining the Plex app version. The host's failed vainfo probe
is not proof that container drivers cannot work. Active lifetime Plex Pass
with the hardware feature was verified without publishing its token.

Acceptance requires a bounded forced **real Plex** transcode with hardware
encode evidence, hardware decode where supported, generated usable segments
and measured production faster than playback. Capture settings versus actual
pipeline separately, test applicable HDR tone mapping independently, and keep
a direct-play control. Stop every test session afterward. A downloaded driver,
a successful VA-API query or a preference flag alone is not acceptance.

`/transcode` is an 8 GiB memory emptyDir with 1001:1001 ownership and mode 0770.
Plex's 12 GiB container memory limit includes this tmpfs consumption. Verify
service-identity create/remove and actual segment throughput after replacement.

## Backups and rollback

The daily `media-backup` CronJob runs `nest::eyrie::media::backup`. It resolves
and verifies the exact retained ZFS PV handles, then uses inventory-backed Bolt
with escalation on Falcon. The task atomically snapshots the five config
filesystems, including databases/WALs, archives each complete snapshot without
following symlinks, stages on local `/var/tmp`, validates compression, and
publishes to direct `/nest/backup/media` with mode 0600. It reads the published
archive back and retains two normal backup generations. Failed snapshot sets
are preserved and block subsequent capture until reconciled, bounding failure
accumulation. Migration rollback snapshots are never selected for cleanup.

Downloads are not archived wholesale; the old downloads source and cutover
snapshot remain the migration rollback, while configuration backups protect
application identity/state. Before closure, run the real backup and restore a
copy in isolated staging; inspect DB integrity and preserved identity. The
fixture test exercises real tar/zstd/rsync and SQLite restore but is not a live
backup receipt.

Rollback: stop all new application writers first; inspect whether post-cutover
requests/downloads/library changes need reconciliation. Restore saved routing
and old integrations/config only from the matching consistent generation,
restore the accepted old host declarations deliberately, then restart the old
services. Never start old and new writers concurrently. Retain PVCs and the
failed generation for diagnosis; do not delete either to simplify rollback.

## Required closure evidence

- Exact accepted source, exact-head CI, image identities and managed convergence.
- Storage health/headroom, six bound retained claims, actual shared-driver test.
- Database integrity and preservation of credentials, requests, libraries/identity.
- HTTPS and redirects from real clients and all app containers, trusted TLS.
- All inter-app test APIs, NZBGet handoff/unpack/import and Plex notification.
- Public Ombi request flow and unchanged authentication/callback behavior.
- Native Plex direct playback and real HW encode/decode/segments/performance;
  applicable HDR result stated separately.
- App persistence after pod replacement; published backup and isolated restore.
- Old writers remain stopped, Runner unchanged, rollback preserved, no secrets
  in evidence. Record any limitation explicitly; landing pages are insufficient.
