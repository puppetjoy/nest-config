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

## Acceptance status

Pending: reviewed publication and exact-head CI; managed host apply and installed
module/plugin byte parity; DEV consumer delivery; DEV-only managed enablement;
real-provider event-driven intervention and independently verified original
outcome; actual Firefox existing-chat and genuine execution-log acceptance;
metrics and immutable receipts; production promotion and final readback.

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
