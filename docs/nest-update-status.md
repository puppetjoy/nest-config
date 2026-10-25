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
| R02 transaction | Locked atomic host-local transaction, safe resume/status and shared A/B state are installed. The shared lifecycle now observes native intent after external-controller restart without replay. | Prove the same state survives the approved real A/B switch. |
| R03 activation/capacity | Activation safety and physical versus logical ancestor-capacity admission are installed. | Evaluate the selected real generation and capacity budget; no quota relaxation or rollback deletion. |
| R04 ordinary A/B | Existing native acceptance/finalize is composed after the retained collector evidence and live accepted status. | Prove ordinary A/B and idempotence in the approved exercise. Retain ambiguous snapshots. |
| R05 waves | Existing update tooling composes complete prepared-only eligibility, bounded native boot observation, acceptance/finalize and surviving user-systemd/Bolt dispatch. Preview/no-reboot remains the default. See [lifecycle](nest-update-lifecycle.md). | Verify managed delivery and the exact separately approved real lifecycle. |
| R06 release | Plain source/input/output/member manifests, pinned inputs and distinct Stage 3 identity/publication roots exist. Explicit compare-old-alias promotion/rollback and selected local placement are delivered by main pipeline 12120; see [publication](nest-release-publication.md). | Actual selected output/storage/resource acceptance remains separately authorized. No Puppet compiler image or code-ID requirement. |
| R07 build DAG | Scoped stage/tool contracts, consumer classifications, native failure propagation and explicit graph compilation exist. Cross-job fixtures exercise predecessor binding and final assembly. Bootstrap separates completed build resources without requiring a gratuitous config source change. | Verify the selected real build's outputs and bootstrap permissions when an actual build is authorized; no automatic live rollout. |
| R08 service availability | Existing survivor/quorum/storage/route maintenance is reused during preparation and immediately before disruptive execution. | Exercise only selected approved service classes. |
| R09 backup | Retention race repaired; full-root local staging, SQLite consistency, atomic publication and a verified post-fix scheduled generation exist. The lifecycle rechecks existing holds and keeps them until explicit release retirement. | Verify selected retained rollback resources in the approved exercise; no replacement capture, prune or live restore merely for evidence. |
| R10 reports | Enclosing lifecycle export copies and reopens the actual sanitized receipt graph from execution controller to caller. | Verify the real handoff and attach concise final deliverables before completion. Historic missing rows stay unknown. |
| R11 acceptance | Existing bounded observations, native Git-versioned apply/repeat, exact historical dispositions and selected boot-bracketed canaries now produce native acceptance evidence. Missing buses refuse. | Verify the approved real cycle. Physical UX remains unobserved until exercised. |
| R12 policy | One schema-5 policy binds existing preparation scope plus disruption window, impact, surviving controller, retained rollback and acceptance through finalize/delivery. | Verify source delivery and the exact approved scope. Preserve console exclusions, kernel exceptions and inventory-backed Joy transport. |

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
