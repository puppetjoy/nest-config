# Falcon Arc: shared-kernel comparison

## Scope and current evidence

Request ^2398 authorizes necessary coordinated software diagnostic/recovery
reboots, preserving acceleration, rollback, essential storage/quorum checks and
restoration. Physical work and speculative live PCI writes remain excluded.

Both i915 and Xe have now lost access to the Arc endpoint. On the failed Xe boot
`89eeaf55-d23a-4ec6-9487-57c42fb93cb6`, pre-recovery readback showed PCI header
`7f`, invalid downstream link-width reads and root `00:02.0` SDES set. External
upstream `03:00.0` still reported 8 GT/s x16. The Xe reset storm is not sufficient
evidence of a scheduler-only defect. Journal rotation lost earlier records;
10:59 is the first remaining matching message, not a proven initiating time.

The November 23 recovery used the preserved i915 payload, without changing the
kernel binary. Boot `e29c8b29-8b3f-4935-a292-aefaaf2a0894` actually binds i915 and
authenticates HuC. Hardware GL rendering, 90-frame host VA-API encode/decode and
real Firefox hardware decoding pass. Plex's real HEVC-to-H.264 pipeline reports
hardware decode and encode and full-pipeline acceleration; actual H.264 output
was consumed and independently probed. These are recovery/function results,
not a causal cure. The managed i915 return is merge `17900b0fec9c220740677e7fd8a258ca96de25bf`;
its source and resulting-main pipelines passed.

## Hypothesis ledger

| Hypothesis | Prediction and present constraint |
| --- | --- |
| Card-internal firmware/fabric or platform-link interaction | Cross-driver configuration-space loss fits. A first-error record or a controlled independent software comparison is needed; SDES alone cannot identify a physical component. |
| Shared kernel/PCI-path defect | A recurrence on an independently selected earlier kernel would contradict a 6.18.56-specific requirement. A short successful comparison cannot prove absence of an intermittent defect. |
| Ordinary host PCI runtime autosuspend | Requires a preceding relevant suspend/resume. GPU/parent suspended-time counters are zero and earlier forced-on policy did not prevent failure. Audio wake errors follow access loss; TuneD is not a causal finding. |
| i915-only or userspace-display failure | Xe also loses endpoint access, contradicting the narrow driver/compositor-only explanation. Userspace can still trigger shared firmware/kernel behavior. |
| HuC authentication defect | Corrected and authenticated before another failure. It is a separate demonstrated defect, not the disappearance cause. |

The earlier observed-good boot and first failing boots used the same kernel #2,
GuC version and relevant probe/IOMMU command line. Retained package history does
not establish a same-weekend firmware or media update. Do not manufacture a
last-good/first-bad upgrade boundary from the symptom report.

## Candidate and qualification

Select only Falcon's kernel tree:

- tag `stable/v6.18.21`;
- immutable fork commit `4477762beaeb2076dc5a623b18a578781b2d26cb`;
- retain current i915 probe policy, firmware bytes, media packages, IOMMU and
  current managed host configuration;
- retain AER and MEI GSC/PXP plus early HuC inclusion.

The authoritative fork tag and host's existing tag resolve to the same commit.
An isolated extraction of each tree's Kconfig and scripts accepted the same
current host configuration using the current native `conf` parser and compiler
context. Both resolutions exited zero. i915, MEI GSC/PXP, AER and Intel IOMMU stay
enabled. The retained complete diff includes older-tree symbol differences:
compiler inline-memset capability, ACPI platform-profile selection, secure-boot
capability and GPU buddy selection. Ordering-only movement is retained too.
This is preliminary dependency qualification, not an older-kernel binary build.
The actual build must run that tree's own olddefconfig, and its resulting config
and firmware compatibility must be checked again before boot.

This deliberately older kernel also omits later stable fixes. It is a temporary
host-specific diagnostic, not a recommended fleet downgrade or established
repair. Restore the fleet-supported selection after the bounded comparison or
when this hypothesis is excluded. Do not leave the diagnostic pin as unexplained
steady state.

## Delivery and bounded comparison

Before publishing an activating selection, hold Falcon's normal Puppet timer and
verify there is no running/queued Puppet transaction. Preserve the complete
current boot payload and selection, current source/config identity and the
separately bootable i915 rollback. Retain the unchanged current kernel modules;
do not overwrite or delete the working 6.18.56 payload to make space. Inspect ESP
capacity and preserve the pre-existing 6.18.21 files before any replacement.

Require exact-head source CI, managed code deployment and the ordinary
`nest::puppet::run build=kernel` workflow. Keep the build/install outcome distinct
from running-kernel identity. If transport disconnects, inspect the same remote
transaction and payloads rather than starting another build.

Notify before the next outage, use fresh boot-bound clean-stop/flush receipts and
one exclusive attempt marker, and reconcile return before another reboot. Restore
captured maintenance states exactly. Recheck actual older-kernel binding, HuC,
accelerated graphics, real Firefox decode and Plex hardware output. Preserve
first-fault AER evidence and stop on a real error; do not loop tests through an
access-loss event. No long soak, repeated endurance run or human certification
is an acceptance gate. A bounded pass is functional comparison evidence only.

IGT 2.3 was source-inspected but not installed or run: its ordinary i915 open/exit
helper invokes active-work cancellation/reset. Do not use the normal IGT runner
on the working desktop under the assumption that a basic GEM test is read-only.
