# Joyride TEST private-content capacity preparation (historical)

The [original capacity preparation](https://gitlab.joyfullee.me/nest/config/-/blob/024215ed4c2a56df2188d7c6f7370ca32843ec77/docs/joyride-test-private-capacity.md)
retains the first-cutover plan, synthetic upload results and earlier backup
failures. Its proposed 10 GiB expansion, pending readiness split and old image
pins are not instructions to repeat that rollout.

The installed TEST readiness split uses the existing Bound 12 GiB data claim.
Live staging quotas were 2 GiB on ops, trusted-test and the worker, and 4 GiB on
the private proxy. These are per-pod limits, not reservations or proof of free
disk or upload throughput. Check actual headroom before publishing; do not
replace the claim, discard retained history or loosen upload boundaries.

Use [TEST readiness isolation](joyride-test-readiness-isolation.md) and
[recurring protection](joyride-test-recurring-protection.md#backup-capture-and-publication)
for current checks. A completed scheduled backup Job is not a restore test;
verify the completed generation and the applicable isolated recovery evidence.
This readback is not private-content publication authority or
[production promotion](joyride-environment-boundaries.md#promote-only-the-app-artifact)
approval.
