# Per-binding Firefox reconciliation correction

Request ^2100 / task t_6b9d4bf4.

The previous global `state.reconciliation` admission check admitted only the
owner and its original acceptance ticket. It incorrectly refused even a
never-seen request scope. A retained reconciliation receipt is history, not a
process-wide request allowlist. The fence now applies only to a binding whose
state is `retired`. Ordinary scopes still use normal resident identity,
ownership, creation receipts, budget and replay protection.

## Already-approved retired requests

A retired request still cannot create through ordinary acquire. A local
administrator may use `--recover-binding` on the resident server after
independently verifying the exact current canonical request and trusted owner
proposal receipt. The grant names scope, approval, immutable archive, current
epoch and a short expiry. It is never accepted in the public command envelope
or the owner viewer. An approval-shaped string from a caller grants nothing.

The grant atomically records `recovery_ready` and its provenance, without any
native action. Normal acquisition then journals a genuinely new creation in
the current resident session. Reapplying the same grant is a no-op, including
when the new creation outcome is uncertain. Old windows are never selected by
URL/title or closed. All archive bytes, original journals and old action keys
remain intact. Terminal scopes, changed epochs, expired grants, conflicting
receipts and pending input refuse. Terminal delivery for a retired binding
records a fence without claiming the unknown native window was closed.

Status distinguishes a retired binding needing application of an existing
approval from one ready for fresh acquisition. Neither state permits input
replay. `FIREFOX_BINDING_RETIRED` is preserved across endpoint and adapter rather
than being mislabeled as a new uncertain native operation.

## Historical activation and verification

The [original incident record](https://gitlab.joyfullee.me/nest/config/-/blob/c7e50b9887f4c57d8384b565ff868542f749d21b/docs/firefox-scoped-reconciliation-repair.md#controller-only-managed-overlay-activation)
retains the one-time overlay procedure, exact approval, image provenance and
qualification results. The archived approval and image pin are not authority
for a new operation. Disposable verification is not installed acceptance.

Use the maintained [generation reconciliation runbook](firefox-generation-reconciliation.md)
for current operator constraints. Preserve history and unknown outcomes; do
not replay input or retry a controller refresh automatically.
