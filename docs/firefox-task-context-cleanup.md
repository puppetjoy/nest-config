# Task-owned Firefox context cleanup (historical)

The [original investigation and acceptance record](https://gitlab.joyfullee.me/nest/config/-/blob/2a665f27e7ce3cc4c8a7a8a2cfa0f50164e0d479/docs/firefox-task-context-cleanup.md)
preserves the controller-only phase, disposable tests, scoped decisions and
later image-rollout preparation. Its image pins, source branches and approval
receipts are historical. Do not use them to repeat a rollout or restart.

Use the [current window lifecycle](firefox-reusable-browser-lifecycle.md#conventional-lifecycle)
for ordinary release and reuse, and [explicit generation reconciliation](firefox-generation-reconciliation.md)
for exceptional recovery. Temporary release or lease expiry is not canonical
terminal cleanup; preserve owner and unknown windows, exact terminal evidence,
and uncertain action journals. Never infer ownership from an old native ID or
replay an uncertain action. A Ready workload does not prove any historical
scope's outcome or authorize retirement of its native generation.
