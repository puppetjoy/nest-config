# Registry retention and maintenance

## Native policy ownership

- Nest owns the existing registry ObjectBucketClaims. Their Rook `bucketLifecycle`
  rules abort incomplete multipart transfers after fourteen days under
  `docker/registry/v2/`. They do **not** expire completed objects. RGW's normal
  garbage-collection grace still applies to physical reclamation.
- GitLab project cleanup settings are declared in
  `data/gitlab-registry-retention.json` and applied through the supported Projects
  API (`PUT /projects/:id`, JSON request body). Read back each project's
  `container_expiration_policy` after applying. Do not use SQL tag-table edits.
- Only temporary config `executor-*` and Joyride `build-*` / `index-*` tags match.
  Policies run daily, retain the newest one hundred matching tags per repository,
  and exclude transfers younger than fourteen days. Floating `latest`, architecture
  tags, immutable commit tags, releases, bootstrap and explicit retention tags do
  not match the expiration patterns. Do not broaden them to `.*`.

## Protected images and rollback floors

Before enabling or changing cleanup:

1. Inventory Kubernetes containers, init containers, controller templates,
   Jobs/CronJobs, host containers, Puppet/Bolt inputs and explicit source pins.
2. Resolve remote manifest/index bytes, verify their digests and recursively
   protect exact architecture children. A runtime `imageID` can be a local digest
   alias; compare it with the requested remote manifest before diagnosing loss.
3. Give every live/pinned/rollback digest that could otherwise lose its last tag a
   durable `retain-<full sha256 hex>` alias in its original repository. GET-verify
   the alias and exact manifest bytes after PUT. Keep source and release ownership
   unchanged. A pin to a temporary CI digest must acquire that alias **before** the
   temporary tag becomes eligible for deletion.
4. Maintain at least ten distinct recent **successful, usable** rollback versions
   for every relevant release/architecture stream. Verify job success, exact
   manifests and blobs; preserve them with retention aliases. Do not infer success
   from a tag's age or a missing pull timestamp. Never remove an old rollback-floor
   alias without first verifying its replacement floor.
5. Native GitLab `keep_n` is per repository, **not per architecture**. The one
   hundred-tag rolling allowance does not replace the explicit per-stream floor.
   Retention aliases are deliberately not automatically expired. Review them with
   ordinary release ownership rather than inventing a second retention controller.
6. Preserve all unique stage/bootstrap and release artifacts. Bootstrap executors
   additionally publish a `bootstrap-*` alias before the successful build receipt
   can be consumed; that alias is outside native cleanup scope. Classify retired
   agent branches separately; do not expire their floating tags merely because a
   metadata import timestamp looks old.

Treat the policy's tag deletions, manifest eligibility, GitLab online-GC review
queues, RGW grace and measured physical capacity as separate stages. Shared blob
sizes must be deduplicated; summing repository sizes double-counts common layers.

## Distribution garbage collection

The native Distribution GC CronJob is a **suspended maintenance template**.
Uncoordinated scheduled mark-and-sweep can delete manifests uploaded after its
mark phase. `concurrencyPolicy: Forbid` prevents overlapping Jobs, not races with
registry publishers. Do not unsuspend it while writers remain active.

For a maintenance run:

- Verify backup/restore/migration Jobs are idle and preserve current references,
  rollback floors and appropriate recovery material.
- Fence every writer to the exact registry bucket. Prefer a verified read-only
  registry maintenance configuration that still serves pulls, or stop the exact
  deployment and verify its pods are absent. Retain the original state for recovery.
- Create a uniquely named Job from the existing suspended CronJob template and
  run `registry garbage-collect --dry-run` first. Review the exact candidate set.
  Run ordinary GC only while the writer fence remains established. Do not add
  `--delete-untagged`: digest-pinned and unique rollback manifests can be untagged.
- Restore the previous serving state on both success and failure; verify actual
  manifest and blob reads and a normal CI publication afterward.
- Allow RGW's ordinary garbage collection to process expired backend garbage.
  Never delete raw object prefixes, bypass its grace, or weaken fullness/durability
  settings to manufacture headroom.

The GitLab registry is different: it uses the registry metadata database and
**online GC**. Never run Distribution's offline collector against that bucket.
