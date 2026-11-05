# Wizard managed delivery ledger

## Release stages

This lane owns installed acceptance, not merely source preparation. Initial
source installation keeps Wizard disabled everywhere. Only DEV Flight Deck is
advanced initially; production remains on its previous accepted source until
DEV acceptance. Existing Talon dispatch ownership, model routing, credentials,
external toolchain ownership and legitimate task waits remain unchanged.

Initial tuple:

- Native: `a8ce4d0b777848ddc6574ff715a116a3e78adfbb`.
- Broker: `9e3120f2263dda8f6f6a3c0d5a1360ac64831bbe`.
- DEV Flight Deck: `366df1a36da31a23341dee6e5fe98fe39335e82d`.
- Production Flight Deck retained: `45163d78b2365d2c52ef7553a93c1e7a5e734837`.

The existing `docs/wizard-source-readiness.md` specifies canonical filesystem
mounts and the normal Bolt render/deploy/apply sequence. This release does not
add a cutover controller, scheduler or lifecycle authority. No environment or
toolchain store is deleted.

## Maintenance observation source advancement

After the initial DEV negative control, Native MR !126 adds the supported
exact-owner observation ingress needed for a recoverable maintenance park.
Advance only Native to `df1b7bbaffb7de71db0d2a51b20bb68af616b205` (tested
source `4d8d17e3bc7b76675edf50e07990d52394ea52e8`, identical tree
`d22da2fd3d8d5200a480c2ef351dcfdc2b0a1a6c`). Broker, consumer pins,
DEV-only enablement and the existing Talon route remain unchanged. The new
observation is opt-in, atomic with a genuine own-run park and not recovery
permission. Preserve DEV controls ^309 and ^310 and their immutable receipts.
No historical park may be retrofitted with an observation. The new source
still requires ordinary managed apply and genuine installed positive acceptance.

## Installed DEV acceptance and production promotion

Ordinary managed apply at Nest `f59ca80d48ad0e7f849dcaf9320332b9f08b6909`
installed the observation advancement successfully. The independent user-manager
unit returned success and exit status zero; its complete retained log records
the catalog and managed gateway refresh. Broker remains at the initial tuple.

The configured DEV watcher and killable Talon supervisor used the existing real
OpenAI Codex route. A supported inert original, DEV ^312, received a real
source-readiness prerequisite, DEV ^311, then exercised an explicitly controlled
retained technical continuation wait through its own bound terminal. This was
not a naturally occurring production incident. The actual park event is 286743,
original run 1519; its opt-in deadline produced signal 2. No service identity was
borrowed and no historical park or callback was manufactured.

The real provider selected Native `resume_wait`. Action
`wa_a0b1835597984a80b3b4daca70744688` settled against the exact park. The original
was genuinely claimed as run 1520, independently verified and consumed the
retained source-readiness report, and completed at event 286756. The existing
watcher independently settled case `wc_2aae19d5c8e74cfdb06e01f325c4a1fd` as
resolved from successor completion, without another model call. This proves the
Native wait-resume lane; it does not claim that the Broker's separate indexed
adapter, scoped repair submission or publication-repair operations ran live.

Observed signal-to-claim was 0.082164875 seconds and signal-to-verified-action
12.869800692 seconds. Actual usage was 3174 provider tokens, one reasoning
attempt, one action and 13 accounted active seconds, with no remaining token
or time reservations. These are measured single-run results, not timing promises.
Read-only samples recorded supervisor RSS up to 79708160 bytes and provider RSS
up to 234422272 bytes; last observed CPU was 1.47 and 4.96 seconds respectively,
not exact lifetime peaks or complete process-tree totals.

The earlier ordinary-success DEV ^309 and fresh prerequisite ^311 completed
without Wizard signals or cases. DEV ^312 remained dependency-gated until ^311
completed. The explicit inert owner hold DEV ^313 remains blocked without a
Wizard signal/case; its intake returned a post-allocation caller-fence refusal,
so its exact created state was read back without resubmission. The older DEV
^310 real-provider null decision remains a negative control, not recovery.
Capacity/authority safety coverage is containing application coverage, not a
claim of newly induced live memory pressure or a live capacity experiment.

Actual Firefox 135 showed Wizard · Talon posts and genuine execution JSONL in
the existing original chat, separately from worker log 1520. Wizard horizontal
scroll changed while chat and worker scroll stayed fixed; worker vertical and
chat vertical scroll were independently exercised. The short genuine Wizard
log has no vertical overflow; no content or CSS was fabricated to make it longer.
DEV serving UID root read its canonical sink at device 42, inode 103135138,
mode 0600, with the producer's exact 1849 bytes and SHA256. Actual serving Git
HEAD is the corrective Flight Deck tuple, with both root-level Python modules
and the frontend packaged. No chmod/chown or reader weakening was used.

Production promotion changes only its consumer pin to that same accepted
Flight Deck revision and adds the production board to Talon's existing mapping.
Deploy and verify the consumer with `deploy_flight_deck_prod` BEFORE ordinary
host apply activates the production board. Native, Broker, route, dispatcher
ownership and other instances remain unchanged. Required remaining readback:
production serving source/mount/readiness/Firefox and bounded API/log checks,
then managed host configuration and installed production observation. Parent
retains final whole-program audit. Safe final receipts and screenshots are task
artifacts; raw rendered Secrets are never public evidence.

Genuine `render_to` runs were exercised for both environments before publication.
The DEV render selects the corrective consumer; the production render retains
its previous accepted consumer. Raw manifests may contain Secrets and are not
public artifacts. Safe structured render receipts are retained separately.

## Rollback and interruption

First disable `kanban_wizard.enabled` in the existing Talon instance through
source and ordinary managed Puppet convergence, without disabling ordinary
Kanban dispatch. Observe bounded in-flight settlement and retain ambiguous
execution receipts. Never delete ledgers, cases, history, worker logs or sinks.
Restore a consumer pin only through existing DEV-before-production deployment
plans. Keep canonical mounts while retained receipts exist. Native/Broker
rollback requires retained-schema compatibility and quiescence; never rewrite
or down-migrate board databases.

A host apply that refreshes this worker's own gateway must run through the
existing bounded independent user-manager pattern after preserving its exact
unit, command and log path. Read back the unit result, complete output and
installed revisions before retrying an interrupted call.
