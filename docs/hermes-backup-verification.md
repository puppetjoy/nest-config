# Verify an existing Hermes backup generation

Use the existing `nest::app::hermes::backup` plan with `verify_only=true` when
checking a previously published full-home generation. Unlike its default capture
mode, this path cannot create or reuse a capture, prune generations, initialize
backup storage, fix permissions, or restore data. It uploads a temporary helper
through ordinary inventory-backed Bolt and removes that helper on exit; this is
not a zero-write operation on the execution host. Backup contents and metadata
are read-only. Normal filesystem access times may advance.

Supply an exact checkpoint, an independently retained expected archive SHA256
(64 lowercase hexadecimal characters without a prefix), and an explicit
`max_age_seconds` from 1 through 604800. There is no default freshness budget and
no selection of the newest available generation. For example, an owner-reviewed
parameter file for the existing plan contains:

```json
{
  "target": "owl",
  "verify_only": true,
  "checkpoint": "REPLACE_WITH_EXACT_EXISTING_CHECKPOINT",
  "expected_sha256": "REPLACE_WITH_RETAINED_ARCHIVE_DIGEST",
  "max_age_seconds": 86400
}
```

Replace both placeholder values before use. Run from the configured project:

```sh
bolt plan run nest::app::hermes::backup --params @/absolute/path/verify-backup.json
```

The default backup account is `joy`; the existing rootless namespace handling
is preserved. All required profiles default to Talon, Star, Beryl and Quill. A
caller may explicitly require a different nonempty profile set. Shared config,
auth and Kanban members are always required, but their contents are never
returned. This remains one profile-inclusive full-root archive, not per-profile
backup generation. Verification and capture/quick/pruning/legacy-cleanup options
cannot be combined. Digest/age options supplied to capture mode refuse before
any host command.

The helper's implemented equivalent, run as the ordinary backup account, is:

```text
hermes-backup-generation verify --backup-dir DIR --checkpoint CHECKPOINT --expected-sha256 DIGEST --max-age-seconds SECONDS
```

It requires the existing private directory, lock, archive and JSON receipt owned
by that account. Missing storage is not initialized. Leaf symlinks and public
permissions refuse without repair. It takes a nonblocking shared lock on the
existing `.generation.lock`; a concurrent capture/prune holding the exclusive
lock fails this check instead of waiting indefinitely or choosing another backup.
Cooperating writers and a trusted backup directory/account are prerequisites;
this is not protection against a malicious process with that account's authority.

Verification checks the completed full-home format, checkpoint/archive name,
required shared/profile coverage, native member/byte counts and complete archive
SHA256 against both the retained expectation and published metadata. Receipt
readback must remain identical under the lock. It does not decompress/extract
private members, run Hermes, create another backup, or perform a live restore.

Freshness is the age of the receipt's strict UTC `created_at` publication time,
evaluated after the complete archive readback: zero through the supplied limit,
inclusive. Future timestamps and stale generations fail. This is NOT the time
of every source file's capture, proof of application/database restore consistency,
or a lease that protects the archive after the shared lock is released. Normal
clock accuracy and native publication semantics are prerequisites. A caller must
retain and independently bind its receipt, check its chosen scope and perform any
separately required restore exercise. Do not weaken the age limit or invoke the
capture path automatically to turn a refusal green.

Success returns schema 1, kind `nest_hermes_generation_verification`, action
`verified`, exact checkpoint/digest, counts, required profiles, publication/check
timestamps and age budget. `restore_verified` and `execution_authorized` remain
false. No private member values or full backup payload appear in this receipt.

This is a working backup-readback prerequisite, not the full host release policy.
The transactional host plan consumes explicit schema-3 `backup_requirements`
before any preparation starts and again at each affected host's initiation, as
documented in `nest-update-waves.md`. Planning and stored observation remain
read-only, and old schema-2 preparation refuses rather than bypassing the checks. Host
rollback/retention, immutable generation/capacity, A/B continuity, catalog/release
attestation and accept/finalize/report integration remain separate unfinished
work. Verification alone never authorizes reset, reboot, cleanup, restore or
release promotion. Existing captures and scheduled retention behavior are
unchanged. Rollback stops using the added verification options; preserve prior
archives, metadata and failure evidence rather than replaying capture or reset.

## Scheduled retention writer source

The four Hermes dashboard backup CronJobs select `backup_config_image`, not the
general rolling `config_image`. The selected immutable multi-architecture index is
`registry.eyrie/nest/config/main@sha256:0004a84df33b744de7660c47e9e9820ebfc0aaf9457f9d82c2f727a7a02dd220`.
Its exact registry bytes and all three member digests match executor pipeline
11922 at config source `0f9f746b4afe0d4206c147e0121844d4241d836b`.
The included helper SHA256 is
`8caf401da04daea60f3c1bed7fa4fd0a8867c746fb2e853648e4ced0950f769c`.
It implements release-bound holds and refuses pruning on malformed hold records.
The amd64 executor was exercised; ARM and RISC-V member publication is verified,
not runtime execution on those architectures.

KubeCM renders this same pin for Talon, Star, Beryl and Quill. Changing the
CronJob template affects only future Jobs; it must not delete, restart or replace
an existing capture merely to obtain uniform image IDs. Before relying on a
production hold, inspect remaining active writers' actual helper bytes as well
as future templates. A newer tag or ancestor source alone is not that evidence.
The current source pin does not prove that arbitrary manual/external pruning
writers are absent, that an application can be restored, or that the selected
backup remains fresh. Existing release/hold checks still apply.

Advance this pin only to a normally reviewed/published executor whose exact
backup plan/helper and architecture receipts have been checked. General config
publication does not automatically upgrade scheduled backup semantics. Rollback
must retain a verified hold-aware executor until every release hold has been
explicitly retired; never restore an old pruning writer to bypass a held backup.
No new backup, hold, pruning or restore is required to deliver this template.
