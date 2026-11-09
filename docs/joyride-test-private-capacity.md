# Joyride TEST private-content capacity and storage

This is source preparation, not a deployment or private-content publication
receipt. Keep the capacity lane separate from readiness MR !717. A main-based
capacity deployment alone would regress that pending topology and must not ship.

## Durable capacity

- Admit 192 MiB only on the exact private content POST. Keep frontend, public,
  method, raw-path, header, authentication and production boundaries unchanged.
- Keep 2048 MiB limits for ops, trusted-test and curated-import. Preserve other
  memory limits, requests and the existing 120-second request budgets.
- Retain the existing `joyride-test-data` CephFS PVC and its identity. Request
  10 GiB rather than 8 GiB; do not replace the claim or delete retained history.
- Give application staging a 2 GiB disk-backed emptyDir. In the readiness
  combination, carry this to ops, trusted-test and the worker's import init;
  unrelated web, internal-web and Stripe scratch limits remain unchanged.
- Give the private nginx proxy a 4 GiB emptyDir. Nginx buffers request bodies
  before application upload admission. Its existing sixteen-connection ceiling
  permits 3072 MiB of simultaneous 192 MiB bodies; 4 GiB leaves 1 GiB for other
  temporary use. This is quota headroom, not preallocated disk or arbitrary
  traffic throughput certification. Do not silently disable buffering or change
  connection admission to evade the transport requirement.

The full-body nginx regression reads its temporary quota from managed TEST
source. With the old 64 MiB fixture, an actual 192 MiB POST returned HTTP 500;
with the prepared quota, the same request reached the isolated upstream with
all 201326592 bytes and returned HTTP 200. Inclusive-cap header admission and
one-byte-over refusal remain independently tested. This is real synthetic proxy
transfer, not a live private import or simultaneous sixteen-upload benchmark.

## Storage evidence and pre-publication checks

The read-only preparation sample found 406847488 bytes free in the existing
8589934592-byte PVC. Expansion to 10 GiB would yield 2554331136 bytes free at
that unchanged occupancy, exceeding the application's 2147483648-byte staging
floor. This is the smallest whole-GiB expansion satisfying that floor, not a
promise of unlimited future retained releases. Recheck actual free bytes before
every publication; retain all history and refuse publication below the floor.

`ceph-filesystem` uses the CephFS CSI provisioner and explicitly permits volume
expansion. The sampled CephFS data pool reported 26808023040 bytes maximum
available; it was not full. Existing slow-operation/stalled-read warnings remain
separate observations, not proof that expansion or a request has succeeded.
After separately approved managed expansion, require Bound status, the same
claim/PV identity, reported capacity and measured filesystem headroom. A source
request alone does not prove CSI/filesystem expansion has completed.

Disk-backed emptyDir statvfs reports backing filesystem capacity, not the
Kubernetes sizeLimit. Verify the actual application and proxy quotas and node
free/allocatable ephemeral storage after rollout. The readiness split has five
application pods plus possible rolling surge and an independent proxy; quotas
are per pod, not a shared reservation. Check scratch, init and surge scheduling
before approving the combined rollout. Tmp is ephemeral and intentionally not
part of persistent backup coverage.

## Backup evidence and unresolved repair

The TEST backup schedule is enabled at `17 */3 * * *`. The sampled latest job
failed with `capture_command_failed`; its predecessor failed too. The retained
last successful scheduler timestamp is `2026-10-23T18:19:23Z`.

Read-only inventory of the existing NFS backup destination found 33 completed
receipts. The latest retained archive is 554117120 bytes: its complete marker,
byte count and SHA256 match the file. Its payload contains `database.dump`,
`files.tar` and `metadata.json`; the file archive covers private, public and maps,
with 1796 regular files matching metadata's count and no links. This establishes
old archive custody and integrity, not a current restore drill or coverage of
newer data. No new capture, extraction, restore or cleanup was performed.

The live tree now has two valid internal symlinks under private/routing. The
pinned backup scanner rejects all nonregular, nondirectory entries, including
those links. That is a concrete current source-contract incompatibility; the
sanitized historical failure code alone cannot identify the precise failed
subcommand. The owning application protection lane must diagnose and repair
safe link custody and restore semantics without following arbitrary paths,
excluding routing data or weakening archive verification. Preserve existing
link identity and all old complete generations. Source preparation does not
repair the running backup. Require a fresh complete capture and appropriate
restore-path proof before private publication.

## Exact integration and delivery gates

Prepare and review the exact combined readiness, capacity and latest delivered
application image, preserving current mail and source changes. The inspected
readiness head is `5259f89d0970e7e28e921bc50b6794d44ac3402e` and capacity's
retained MR head is `a1d328838bf0d4a3c18975a228fa8a4d1e22fc50`.

The verified installed multi-route delivery was application main
`dd33ad9d448b59ddabc156fb1f61c66be953a8a2`, pipeline 13169, preview job 57595.
A newer approved route-load delivery superseded it during preparation: main
`8f087daef3dd9126d976a72083f7113544f6ba92`, pipeline 13177, preview job 57634,
image `registry.gitlab.joyfullee.me/joy/joyride/app@sha256:30155a78c4d5652e6499cbe2f3598daf7246c3256bb7755a19d0a705f663166d`.
The prepared pin follows that newer installed source, retaining multi-route
support rather than rolling route-load code back. Refresh again before
publication and do not regress a later delivery.

Readiness's bootstrap recipe hashes its import init configuration. Changing the
curated-import memory limit changes that recipe: recompute the shared
`BOOTSTRAP_CONTRACT` for the worker and all four readers in the exact integration
source. Keep their recipe identities equal. A clean render alone would miss a
stale recipe; run the containing component-readiness suite against actual output.

Use the supported retained same-MR successor publication path and successful
exact-new-head CI. Old green CI does not certify unpublished pin/storage changes.
Preserve refusal evidence rather than raw-pushing, renaming branches, duplicating
MRs or borrowing approval. The first readiness selector migration remains
non-zero-gap and needs an idle journal/queue and an explicit availability plan.

A future exact-source approval must separately name the combined MR heads,
image, existing-PVC expansion, temporary quotas, backup repair/verification and
managed TEST rollout. It must preserve graph bytes, release selection, complete
existing member/media/waiver/review/revision rows and rollback history. No merge,
apply, restart, selector cutover, private publication or production authority is
provided by this preparation. Luna remains the private-content publisher.
