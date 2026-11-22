# Falcon Arc: software/platform investigation after AER recurrence

## Current outcome and boundary

The blackout repair remains incomplete. The last installed accelerated check
failed; no further GPU workload was run in this investigation. Joy reports
that seating and power are sound. Physical inspection is not a prerequisite
and the previous inspection proposal is not proceeding.

This pass used read-only inventory-backed Bolt commands and local source
qualification. It did not reboot, shut down, rebind, change PCI power policy,
change BIOS settings, stop host services or release maintenance holds.
Falcon still reports boot `00a869e2-bfc9-4cc7-b2f6-e13c3895ce66`, kernel
6.18.56 #3. The Puppet timer, kubelet and NFS are active. That is a service
readback, not evidence of working graphics.

The earlier source-preparation report is historical. Its AER/firmware changes
were subsequently installed through MR 782; the activation/recurrence report
attached to the task records that failed acceptance and full restoration.

## New comparisons

### Kernel, firmware and onset

The clean tracked kernel source is
`a90c2d8f15fbb50a748b288d27f6509f43fc9730`. Its only untracked files are
`build.log` and `build.sh`; the tracked source has no local diff.

Retained kernel journals identify access-loss signatures in these boots:

| Boot start | First retained access-loss signature |
| --- | --- |
| November 15, 14:42 | November 21, 05:31:42.867226 |
| November 21, 12:49 | November 21, 15:49:27.474419 |
| November 21, 16:09 | November 21, 16:12:36.502044 |
| November 21, 16:18 | November 21, 16:20:46.833849 |
| November 21, 18:29 | November 21, 18:32:12.944926 |

The immediately preceding November 6–15 boot has no match for the queried
GuC-corruption, unreliable-MMIO, GPU-HANG or DMAR-fault signatures. It ran the
same kernel 6.18.56 #2, GuC 70.53.0 and relevant i915/IOMMU command line as the
first two failing boots. This is a useful earlier observed baseline, not proof
that every workload or policy transition was identical or that no silent
fault occurred. It weakens a same-day kernel/GuC update explanation. Kernel
#3 changed diagnostics and early HuC availability, not the original trigger.

### Frequency error is not a TuneD-write receipt

In the exact installed `gt/uc/intel_guc_slpc.c`, the error text
`Failed to send set_param for min freq` comes from `slpc_force_min_freq()`.
The file documents waitboost: i915 temporarily raises the minimum to RP0
while a submission has waiters and lowers it afterward. Thus the observed
2400 MHz argument is consistent with ordinary internal waitboost, not proof
that an administrator or TuneD forced that minimum. The failed GuC send is
logged after descriptor access already returns all ones.

The installed TuneD video plugin supports Radeon/AMDGPU settings, and the
retained TuneD startup log reports `instance video: no matching devices
available`. TuneD's HDA audio policy is real, but neither this plugin nor the
later audio-resume error proves initiation of the Arc fault.

### Existing fixes are not missing patches

The installed i915 source already retains discrete-GPU autosuspend control
`on` by default, the protection described by upstream commit
`66eb93e71a7a6695b7c5eb682e3ca1c980cf9d58`. Promoting the emergency udev rule
would duplicate this protection, not identify a missing repair. Earlier
forced-on policy did not prevent recurrence. GPU internal RC6/GuC power
control is distinct from PCI runtime suspend and is not disabled by that rule.

The source also contains the CPU-qualified DG2 G8 workaround
`0937c6e7113e07a67301b809ec824b032b3821bb`. It is not a justified new patch to
apply. The external link's captured ASPM-disabled state does not support
blindly changing link-power policy. No matched corrective upstream patch was
identified by this bounded search; that is not a claim that none exists.

## What AER does and does not establish

The first AER message names the Arc endpoint as the fatal-error source.
Root completion timeout follows, then GuC descriptor corruption/all-ones
access. The endpoint's initiating AER status is not captured in that first
message, so its exact fatal subtype remains unknown.

The root's Surprise Down status is recorded later, after an initial failed
recovery attempt. It must not be promoted to a timestamped diagnosis of the
initiating physical link event. The subsequent automatic link reset and
zeroed upstream bus/decode state are recovery fallout, not pre-fault state.

The 60-second pre-fault kernel windows for the first two incidents contain
no preceding logged PCI reset, suspend or DMAR fault. The diagnostic boot
has VFIO activity on the other root port earlier in startup, but not an
immediate matching Arc reset before the fatal message. These negative log
samples cannot exclude unlogged PM callbacks, internal GPU firmware actions
or workload-sensitive defects.

## Ranked falsifiable software/platform hypotheses

1. **Card-internal firmware/GT power or fabric failure.** Whole-device access
   loss and an endpoint-origin fatal message fit this better than an isolated
   display/compositor crash. Capture host PM events and first AER/GPU events
   on one bounded return workflow. A preceding host transition would shift
   priority toward hypothesis 2; no host transition would narrow, not prove,
   this hypothesis. Do not disable GuC submission or switch to Xe: i915 and
   VA-API are required, and no supported causal workaround is established.
2. **Host runtime-PM/audio sequencing interacting with the card.** A relevant
   suspend/resume callback must precede endpoint loss. Precise callback and
   runtime-PM tracepoints can test that prediction without changing power
   policy. Later D3hot errors alone fail this test. Existing forced-on
   recurrence weighs against the simple GPU-D3cold-only version.
3. **Workload-sensitive i915/GuC/LMEM interaction on the small-BAR platform.**
   The observed 256 MiB BAR and normal waitboost are context, not diagnosed
   defects. Mark graphics/video stage boundaries and correlate first failure
   with the trace. A failure before the marked workload contradicts that
   workload as the necessary trigger. One passing bounded run is functional
   evidence, not proof of a permanently corrected intermittent crash.
4. **IOMMU or another device's reset interfering with Arc.** Require a matching
   first fault or reset affecting Arc's actual root path. The queried windows
   supply neither. Do not disable IOMMU, disturb guest assignment or change
   PCI allocation as a speculative test.

## Separate source-prepared HuC dependency correction

`data/host/falcon.yaml` now selects only:

```yaml
CONFIG_INTEL_MEI_GSC: y
CONFIG_INTEL_MEI_PXP: y
```

The exact running source's `check_huc_loading_mode()` rejects DG2 GSC-loaded
HuC if either option is disabled. The existing kernel has both disabled;
its installed HuC finds the firmware but fails initialization. This is a
proven missing-dependency defect, not an established explanation of endpoint
loss. It is corrected in prepared source only, not installed or claimed as
the blackout cure.

No full protected-content feature is added. In this kernel, the Makefile
always builds `intel_pxp.o`, `intel_pxp_huc.o` and `intel_pxp_tee.o`;
`find_gt_for_required_teelink()` supports HuC's backend independently of
`CONFIG_DRM_I915_PXP`. Enabling full DRM PXP is unnecessary for this repair.

### Executed source qualification

- Read-only export of the host's actual Kconfig tree, helper scripts, native
  `conf` binary and existing `.config`; no host build/config write.
- Local baseline and candidate `conf --olddefconfig` both exit zero.
- Candidate relative to the normalized baseline enables exactly MEI GSC and
  MEI PXP. The only additional visible line keeps `DRM_I915_PXP` disabled.
- Local compiler-context normalization differs from the host in the compiler
  text and toolchain capability fields; the retained receipt exposes that
  delta. This is Kconfig dependency qualification, not a host binary build.
- `pdk validate` passes in the repository's immutable CI image.
- Focused public Nest and systemd-bootloader specs pass: 1,133 examples,
  no failures. No new leaf-resource spec was added for the Hiera wiring.
- No remote publication, merge, installed-kernel rebuild or activation in
  this pass. Exact-source release CI and an actual managed build remain
  required before any future activation.

Kconfig export SHA256:
`48280e0bf123c4e4045fe4e7fd73090e3d3b3864d6e9b5a024542b177cc4e2b0`

## Next discriminating operation, not yet authorized

A software-only planned return boot with passive event capture is the next
useful live boundary. This requires fresh coordination because the current
boot is wedged and the previous boot approval is consumed. It is not a
physical-inspection request or authorization to perform one.

Qualify the prepared source through release CI and the managed build first.
For one coordinated boot, retain i915, hardware video acceleration, present
PCI policy and the existing storage/CI restoration procedure. After boot,
use an isolated bounded trace instance filtered to Arc's real PCI path, using
the verified `rpm_suspend`, `rpm_resume`, `rpm_return_int`, `rpm_status` and
PM-callback events. Check actual available events/fields before configuring
that instance; the running kernel already enables event tracing. Do not use
MMIO register dumps or a new power/driver setting as instrumentation.

Capture stage markers around the existing short GLX rendering and synthetic
VA-API encode/decode workflow. Stop immediately on the first real error;
do not replay the workload, issue a second reset, or leave an indefinite
monitor. Retain the first AER message and callback ordering, and restore the
trace instance and all task-owned pauses. A HuC authentication result is
reported separately from the accelerated workflow and the blackout cause.

## References and retained receipts

- Source preparation and diagnostic activation reports attached to task
  `t_72166060`; precise AER log is attached separately.
- Local receipts under `rollout-evidence/falcon/evidence/`: software comparison,
  source/dependency reads, kernel history, upstream commit search and Kconfig
  qualification. Raw diagnostic captures remain untracked.
- https://github.com/torvalds/linux/commit/66eb93e71a7a6695b7c5eb682e3ca1c980cf9d58
- https://github.com/torvalds/linux/commit/0937c6e7113e07a67301b809ec824b032b3821bb
- https://docs.kernel.org/PCI/pcieaer-howto.html
