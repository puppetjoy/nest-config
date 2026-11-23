# Falcon controlled Xe comparison

## Scope and evidence

Joy authorized a rollbackable Xe comparison in request ^2398, including managed
source delivery and a coordinated boot. This is not an established correction
for the intermittent PCIe disappearance. The latest i915 failure begins with
root-port Surprise Down before GuC access loss; the initiating cause remains
unproven. No physical or BIOS change, live PCI power adjustment, or driver rebind
is part of this comparison.

The installed media-libs/libva-intel-media-driver 26.2.4 lacks upstream commit
[c3e1867d6de236102951ee40a75319dbf54beb79](https://github.com/intel/media-driver/commit/c3e1867d6de236102951ee40a75319dbf54beb79).
The exact cached source lacks both small-BAR detection and the visible-VRAM
allocation flag. Its buffer-manager source SHA256 is
`c0beb20bb3caae9c8850af0872898e3a7778adc906ec5e6ee4c823f0cce25466`.
The installed iHD binary matches Portage's retained manifest and lacks the new
small-BAR diagnostic marker. This is a specific explanation for the previous
Xe initialization failure on a 256 MiB BAR, not proof of the i915 blackout cause.

## Managed change

Backport the unmodified upstream patch only to Portage package version 26.2.4.
It detects CPU-visible VRAM smaller than total VRAM, requests visible allocations
and permits system-memory placement if that region fills. It does not replace
hardware media processing with software decoding. The version-qualified patch
must be requalified or removed when the package advances; do not blindly apply
it to a version already carrying the upstream fix.

Falcon's command line excludes DG2 from built-in i915 and permits Xe probing.
The existing kernel has Xe as a module with display support; AER remains enabled.
No kernel power-policy change is bundled. Retain the i915 HuC firmware and MEI
configuration for a usable rollback rather than removing it during comparison.

## Delivery and rollback boundary

Before changing boot selection, retain a complete verified kernel, initrd,
modules, boot entries and selection, plus the current boot environment. Keep a
separately selectable i915 entry referencing its own complete payload, not only
a saved configuration. Hold Falcon's Puppet timer during partial delivery.
Deploy through the repository Bolt Puppet plans, verify the delivered patch,
then source-rebuild this exact media package with binary-package reuse disabled.
Verify the new installed binary and retained build evidence before the trial.

Use the current approved maintenance owner and a fresh ledger for the actual
outage. Restore preparation-only global pauses while source work and CI run.
Before the coordinated reset, preserve essential storage/client quiescence and
flush checks; do not wait for natural backup completion when cancellation is
needed. Never repeat an uncertain reset without reading its attempt receipt and
boot identity. Retain rollback bytes until installed acceptance is complete.

## Required bounded installed acceptance

- Verify the new boot ID, actual Xe binding and effective probe command line.
- Run accelerated graphics, rejecting llvmpipe/software rendering.
- Demonstrate Firefox hardware decoding of actual video, not just VA-API
  capability enumeration or browser preference values.
- Exercise representative required Plex hardware transcoding, checking actual
  decode/encode paths and output, not just `vainfo` or generic FFmpeg support.
- Preserve AER and kernel error evidence throughout; stop on the first fault.
- Restore all task-owned maintenance states and check serving/storage health.

DG2/Xe HuC and low-power bitrate-control limitations are separate from the
small-BAR fix. Upstream [issue 2046](https://github.com/intel/media-driver/issues/2046)
describes misleading advertised rate-control capabilities. A CQP synthetic
encode does not establish the required Plex bitrate-controlled workflow. Do not
silently accept software fallback or reduced media capability; retain i915
rollback if the required real workflow fails.

A passing bounded comparison establishes installed function in that interval,
not proof of the intermittent blackout's cause or permanent stability. No long
soak or owner certification is a completion requirement.
