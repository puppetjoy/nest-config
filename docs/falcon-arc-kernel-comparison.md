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

## Bounded installed result and removal of the diagnostic selection

The managed 6.18.21 build completed through the ordinary Bolt plan. Its exact
Puppet report records the accepted merge, no failed resources, and successful
kernel build, module rebuild and kernel-install events. The ESP kernel matches
the built image, both prior 6.18.56 payloads and their entries remain unchanged,
and the initrd includes HuC/GuC and ZFS. Actual olddefconfig retains i915, MEI
GSC/PXP, AER and Intel IOMMU; the complete normalized config difference is
retained with the investigation evidence.

The coordinated comparison reset reached boot
`e8cbc78d-af06-4cd8-bdc3-af46cba6526d`, actually running 6.18.21 #5 on i915.
HuC authenticates for all workloads. Hardware GL rendering, 90-frame host
VA-API encode/decode with zero decode errors, and actual Firefox hardware
playback pass. Plex also passes a real HEVC-to-H.264 hardware pipeline with
bitrate limiting requested, VA-API decode and encode, and independently probed
consumed output. Actual output is 718 × 306, not the requested maximum
1280 × 720. The exact disposable session was removed.

The reset connection loss was reconciled against the new boot and its exclusive
receipt, not replayed. Both PostgreSQL instances, RGW and all three local OSDs
had fresh exit-zero receipts before storage flush. Noncritical client nonzero
exits remain recorded. Kubernetes/API startup initially waited for BGP routes;
Falcon subsequently became Ready. All captured runner and Kubernetes scheduling
states, node schedulability and the normal Puppet timer were restored. GitLab
and PuppetDB startup failures are retained separately from GPU evidence.

No endpoint loss occurred during this bounded comparison. That establishes
function on the earlier tree, not a causal correction or exclusion of a
6.18.56-specific intermittent defect. Retire the temporary host kernel overrides
after this comparison: future managed selection returns to the supported fleet
kernel. The current working comparison session need not be interrupted merely
to retire source policy. Retain its module tree and the complete rollback
payloads; do not report a source-selection change as a running-kernel change.

## Further source triage — not additional mitigations

Review of the actual selected fork's PCI/DRM/IOMMU history does not identify a
matched causal patch. In particular:

- `10021c2d33061b7704129bc4cdfcacf9cc396349` fixes ASPM reconfiguration after
  entering D3hot. It is already in the failing 6.18.56 tree, not a missing fix;
  zero GPU/parent runtime-suspended time further limits this explanation.
- `3ab6f4eccbbf508bd5a52fa6ad10d1e52f609788` fixes multi-function ASPM setup
  ordering. It concerns capability initialization, not proof of the observed
  later failure; it is also already in the failing tree.
- `301288f85679aa76f6307d0fe2c0cb31baebc0f6` and
  `6beadccc432cf50cfb16bc061109c03b2dcb2654` avoid spurious zero-length or
  boundary config-access wakeups. Neither is evidence that such an access
  initiated Falcon's earlier faults.
- `9c698af5c2a12035d093244ca37e3c0971fd05e4` changes lifting a 2.5 GT/s clamp
  during failed-link retraining. The measured external link is 8 GT/s x16;
  the on-card 2.5 GT/s fields must not be mistaken for the external link.

[Intel media-driver issue 1750](https://github.com/intel/media-driver/issues/1750)
contains an A750 report with the same on-card bridge IDs, inaccessible-device
errors and all-ones register reads, but no accepted causal repair. Later reports
explicitly contradict the early claim that disabling CPU C-states universally
fixes it. Do not promote that suggestion, display power options, or unrelated
integrated-GPU FIFO reports into a Falcon correction. Generic online recipes
that conflate PCI ASPM with D3, combine multiple power changes or suggest
world-writable GPU devices are not qualifying evidence.

The remaining discriminator requires a real first-fault trace or a concretely
matched defect, not a long soak or user certification. Preserve the distinction
between successful managed diagnosis/function and the still-unresolved
initiating endpoint-loss mechanism.

## Passive first-error retention

The prior Xe reset storm rotated away the initiating journal record. The
source-managed `nest::host::falcon::arc_diagnostics` now provides a small,
boot-scoped tracing instance, `falcon-arc-first-fault`, to retain the available
PM/AER ordering instead of relying on a later storm tail. This is diagnostic
instrumentation, not a blackout repair or another stability gate.

The oneshot service enables only Arc-topology AER and device/runtime-PM events.
A conditional `traceoff:1` trigger freezes that instance on its first Arc
uncorrected AER event (nonfatal or fatal, not corrected errors). The ring is
256 KiB per CPU; older prehistory can be overwritten before the trigger, so it
is not a complete lossless historical trace. No scheduler, arbitrary application
arguments, media contents, GPU workload, driver reset, PCI write or power-policy
change is recorded/performed by this helper. Global tracing and unrelated
instances are untouched. There is no userspace monitoring loop or timer.

The real kernel's filter/count/freeze behavior was exercised with harmless
process-exec events in a disposable separate instance: a nonmatching event did
not consume the trigger, the first matching event and preceding marker were
retained, tracing stopped, and a second matching event did not overwrite the
capture. No AER or hardware fault was injected. `CONFIG_TRACER_SNAPSHOT` is not
enabled; an initial snapshot attempt correctly failed and its fixture instance
was removed. The supported traceoff mechanism avoids another kernel rebuild.
Isolated helper checks also cover armed/frozen idempotence, changed-spec and
wrong-boot refusal, missing/unknown-instance preservation and exact device scope.

On another recurrence, before any reset, read:

- `/usr/local/sbin/falcon-arc-first-fault --status`;
- `/sys/kernel/tracing/instances/falcon-arc-first-fault/trace`;
- that instance's `events/ras/aer_event/trigger` and per-CPU stats;
- the exact current boot's earliest bounded kernel journal and PCI/AER state.

Service restarts and ordinary Puppet convergence must not clear or rearm an
existing same-boot capture. The helper refuses unknown or mismatched state
rather than deleting it. Trace memory is volatile: retain it before reboot.
It starts only when the service runs and cannot recover earlier boot events,
events absent from these tracepoints, or evidence after a complete host crash.
A successfully armed recorder is not evidence that a real failure was captured.

Removal boundary: after actionable first-error evidence and an accepted causal
repair, preserve the capture, stop/disable the oneshot, and remove its class
inclusion, helper and unit from source and the retired live files. Do not clear
its tracefs instance while evidence is still needed. No human certification or
extended observation period is required for the installation phase.
