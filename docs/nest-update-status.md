# Practical Nest update completion checklist

This is the current implementation scope for R01–R12, not a new update platform.
The custom immutable Puppet compiler design is retired. Normal r10k/OpenVox,
Git configuration versions and native catalog/report outcomes are sufficient;
per-catalog module-byte attestation, cross-platform cache censuses and historical
compiler-image reconciliation are not release requirements.

## Current behavior and remaining work

| Recommendation | Implemented behavior | Genuine remaining work / acceptance |
| --- | --- | --- |
| R01 checked reset | Checked native exits, JSON and read-only planning are installed on Owl and Builder1. | Consume this interface in the shared lifecycle exercise; do not repeat completed fault tests on live data. |
| R02 transaction | Locked atomic host-local transaction, safe resume/status and shared A/B state are installed. | Compose continuation through reboot and prove the same state survives the approved A/B switch. |
| R03 activation/capacity | Activation safety and physical versus logical ancestor-capacity admission are installed. | Evaluate the selected real generation and capacity budget; no quota relaxation or rollback deletion. |
| R04 ordinary A/B | Acceptance/finalize and default-preview Bolt interface are installed. | Call finalize only after collected acceptance; prove ordinary A/B and idempotence in the shared exercise. Retain ambiguous snapshots. |
| R05 waves | No-reboot default, failed-prepare refusal, domain-aware planning, preparation and reboot observation exist. | Compose prepared-only reboot, existing external controller continuation, acceptance and finalize into the existing update plan. |
| R06 release | Plain source/input/output/member manifests, pinned build inputs and distinct Stage 3 identity/publication roots exist. | Finish compare-old-alias promotion/rollback and selected-root placement. Verify complete output assembly without an OS rebuild. No Puppet compiler image or code-ID requirement. |
| R07 build DAG | Scoped stage/tool contracts, consumer classifications and native failure propagation exist. | Finish predecessor/final assembly and the old-executor → OpenBolt → successor edge in one nonpublishing integration. Enable only the supported build path, never automatic live rollout. |
| R08 service availability | Existing survivor/quorum/storage/route maintenance is used during preparation. | Reuse it immediately before disruptive execution; exercise only selected service classes. |
| R09 backup | Retention race repaired; full-root local staging, SQLite consistency, atomic publication and a verified post-fix scheduled generation exist. | Apply backup freshness and retained rollback policy to the selected lifecycle; no replacement capture, prune or live restore merely for evidence. |
| R10 reports | Sanitized host/supervisor receipts and durable scope recovery exist. | Enclosing lifecycle must copy and reopen actual referenced reports, then attach concise final deliverables before completion. Historic missing rows stay unknown. |
| R11 acceptance | Bounded boot/system/user-manager/network checks and invocation-bound main apply/converged repeat exist; a real mutable-server pair is retained. | Compose existing observations, native Git-versioned reports, historical failure dispositions and targeted canaries. Physical UX remains unobserved until exercised. |
| R12 policy | Scope/window/exclusions/kernel/failure-domain and backup policy feed preparation. | Consume one policy unchanged through reboot, impact, rollback/retention and accept/finalize. Preserve console exclusions and inventory-backed Joy transport. |

## Finite integration path

1. Remove compiler-only CI gates, frozen-tree/cache helpers and stack guards.
   Restore TEST through the existing OpenVox chart and ordinary code deployment;
   verify ready service, normal environment paths and actual catalog compilation.
   Production deployment selection, trust and credentials remain unchanged.
2. Complete the R06/R07 nonpublishing graph/assembly and bootstrap check together.
   Preserve existing successful builds and failure-propagation evidence. Explicit
   promotion/rollback is source functionality, not permission to promote now.
3. Complete one policy-bound composition in existing host update tooling:
   prepare → prepared-only reboot → observation → health/main apply/repeat →
   accept → finalize → durable report handoff. Shared fault fixtures cover failed
   preparation, ambiguous completion, restart and missing health/bus evidence.
4. After release/generation/capacity prerequisites exist, use an exact reviewed
   separately authorized host canary to prove A/B continuity and the complete
   lifecycle. Resolve existing exact approvals before asking for another one.

Source tests, merge and deployment are not live reset/reboot acceptance. This
program remains unfinished until the applicable original outcomes are verified.
No broad OS rebuild, release alias promotion, host reset/reboot, quota change,
backup pruning or live restore follows from ordinary source cleanup.

## Compiler simplification and rollback

The executor still records its ordinary source/module inputs and build receipts.
OS release manifests, debug/CPU/platform distinctions and native report checks
remain. CI no longer generates, pins or deploys custom Puppet compiler images.
`nest::puppet::deploy` uses r10k and expires the native environment cache.
OpenVox startup explicitly selects the normal environment and module paths.

Retained registry images/tags are not pruned by this change. Before restoring
TEST, preserve its selected snapshot/runtime bytes privately on existing
persistent server storage; these are inert rollback material, not an additional
publication service. Remove the obsolete persisted native hook symlink as a
one-time live repair, not a permanent migration script. No CA or client identity
is changed. Do not remove encrypted Hiera credentials or persistent volumes.

Rollback stops automation at the failed phase and preserves receipts, backups
and A/B. If compiler restoration itself needs rollback, use the saved deployment
and snapshot material under supervision; do not blindly revert mixed-purpose
commits or turn the retired custom compiler design back into a release gate.
