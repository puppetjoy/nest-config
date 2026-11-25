# Original Wizard source readiness (historical)

The [complete historical record](https://gitlab.joyfullee.me/nest/config/-/blob/64a20661df0740b13bdfe43114cb4d27efe465f2/docs/wizard-source-readiness.md)
is retained in Git. Do not replay its source pins, opt-in sequence or rollout.

For current Hermes and Broker releases, use [Routine Owl delivery](hermes-managed-source-transition.md#routine-owl-delivery).
For Flight Deck, use the [source rollout runbook](flight-deck-source-rollout.md);
DEV refresh and production promotion remain separate.

The managed Wizard role and its supported recovery remain in use. Keep the
canonical board mounts, ledgers, cases, logs, approvals and execution receipts.
Do not replay uncertain effects or reuse a historical rollout approval.
