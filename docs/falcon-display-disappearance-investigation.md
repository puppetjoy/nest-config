# Falcon Arc disappearance: investigation and source preparation

## Status

**The blackout trigger is unresolved. This is not a completed crash repair.**
The prepared source corrects a demonstrated early-firmware omission and enables
PCIe error reporting/recovery in a future Falcon kernel. Neither change has
been installed, and neither is evidence that the initiating fault is fixed.
Hardware acceleration remains enabled. No reboot, driver rebind or live PCI
power-policy write was performed by this task.

## Verified timeline

Retained journals, read through inventory-backed Bolt, show:

| Incident | First GPU access failure | Later audio bridge failure |
| --- | --- | --- |
| November 21, 05:31 | 05:31:42.867226, GuC CT head/tail/status all ones | 05:31:42.960274, `04:04.0` D3hot to D0 inaccessible |
| November 21, 15:49 | 15:49:27.474419, same CT signature | 15:49:27.912589, same bridge failure |
| November 21, 16:20 | 16:20:46.833849, same CT signature | Emergency power-policy intervention already preceded this incident |

The initial incidents precede the emergency interventions. Subsequent
forcewake reads across unrelated domains, reset-control reads and display AUX
reads return all ones. GPU reset fails; Firefox crashes afterward. This
establishes a device-access-loss failure class, not the event that caused it.
The audio bridge is not established as the initiator. The later incident is
counterevidence to a simple claim that forcing GPU/bridges on repairs the bug;
it does not prove the preceding audio wake caused it.

## Current topology and diagnostic blind spot

The Arc's host root port is `0000:00:02.0`, not `0000:00:03.0`:

```text
00:02.0 -> 03:00.0 -> 04:01.0 -> 05:00.0 (Arc A750, i915)
                     04:04.0 -> 06:00.0 (Arc audio)
```

The external link was 8 GT/s, x16, with ASPM disabled. The on-card virtual
links advertise 2.5 GT/s, x1; those values alone are not a degraded external
link. The current GPU and bridges are D0 with no recorded runtime suspension
in this boot at the topology capture. The audio endpoint is D3hot/suspended.
Its settings remain `power_save=10` and `power_save_controller=Y` despite the
emergency modprobe file; TuneD balanced reapplies that policy.

The running kernel has `CONFIG_PCIEPORTBUS=y` but **CONFIG_PCIEAER disabled**.
AER reporting/recovery is therefore absent. The `_OSC` log did not advertise
AER support; that is not evidence that firmware refused a request for it.
AER status registers can be inspected, but healthy post-reboot samples do not
recover the missing incident-time link/power state. The current host has no
`ipmitool`, so this task obtained no BMC voltage/event evidence.

## Ranked, falsifiable mechanisms

1. **External PCIe path or card-wide power/access loss.** Predicts invalid
   configuration access or root/upstream link/error evidence during a fault,
   with both GPU and audio affected. Valid configuration and stable external
   link during simultaneous BAR failures would narrow this to the card's
   internal fabric/power path instead. Historical logs lack that snapshot.
2. **GPU/card internal firmware or power/reset failure.** Predicts valid
   upstream configuration/link state while GPU BAR/LMEM access fails; a
   preceding reset/power event or matched upstream defect would strengthen
   it. No matched corrective upstream patch was established.
3. **Host runtime-PM sequencing, including audio.** Requires a relevant
   transition *before* access loss. The later logged audio error and TuneD
   conflict do not supply that proof. A failure while the GPU and bridges
   have never runtime-suspended weighs against simple D3cold-only theories.
4. **A GuC command or browser-only hang.** Predicts substantially intact
   device access outside that subsystem. Widespread all-ones reads and the
   later audio-bridge failure weigh against this narrower explanation.

Missing HuC is a separate, demonstrated defect: built-in i915 requests it
before the real root mounts, but the active initrd omits the file. It was
already absent in most retained boots. It does not explain whole-device
access loss. Likewise, the reduced 256 MiB BAR and existing TuneD policy are
not demonstrated last-good/first-bad transitions.

## Prepared desired state

- `nest::initramfs_firmware` provides an explicit required early-firmware list.
  Falcon selects `/lib/firmware/i915/dg2_huc_gsc.bin`.
- The private dracut implementation writes `20-firmware.conf`, requires the
  firmware package and uses the existing dracut-to-kernel-install refresh
  boundary. Empty configuration removes only this managed drop-in.
- Falcon selects `CONFIG_PCIEAER=y` for PCIe diagnosis and the ordinary kernel
  recovery path. This is diagnostic/recovery enablement, not a proven cure.
- i915 selection, VA-API, IOMMU and guest-device assignment remain unchanged.

Do not publish the emergency runtime-power or audio files as a proven fix.
They remain explicitly temporary live drift, unchanged by this task. Before
final closure, reconcile/remove those exact files in a coordinated convergence
without triggering live power transitions or preserving incident history as
permanent Puppet migration machinery.

## Executed checks

The stock local PDK image and registry `latest` tag were stale relative to the
Gemfile: frozen offline dependency resolution rejected missing `syslog` before
validation. Retaining the generated ignored lock and using the repository's
actual CI image resolved the prerequisite without changing dependencies:

```text
registry.gitlab.joyfullee.me/nest/tools/pdk@sha256:7a4e1fcb8b186055e35c232af8273997023839246f712408178d8e725a134673
```

- `pdk validate`: passed after correcting the new parameter's alignment.
- `pdk test unit --tests=spec/classes/nest_spec.rb,spec/classes/nest_base_bootloader_systemd_spec.rb`:
  1,133 examples, no failures. Includes the public early-firmware regression,
  dependency-complete catalog compilation and the direct `kernel-install`
  subscription to `Class[nest::base::dracut]`. This subscription, not the
  unrelated systemd-daemon-reload resource, carries dracut file changes.
- An isolated dracut build under `/var/tmp` included DG2 DMC, GuC and the
  630,784-byte HuC file. The candidate was removed after verification; no
  loader entry or installed image was replaced. The active initrd checksum
  remained `c8a5ac55be0f77608fe40f8b422cd1de4658faae55f9f6806481203a71e454e9`.
- On unchanged boot `26ec2bac-e962-4b41-ba76-82d8fb25cd0b`, from 16:53:46
  through 16:53:59, hardware GLX rendering ran for 12 seconds near 60 FPS.
  iHD 26.2.4 encoded and hardware-decoded 90 synthetic 720p H.264 frames;
  decoding reported no errors. No kernel messages appeared during the run.
  Temporary synthetic media was removed. This is a baseline, not installed
  acceptance of the proposed source or a stability certification.

No claim is made about Firefox video decode, Plex, physical audiovisual
quality, an AER-capable boot or elimination of future blackouts.

## Next decision boundary

There is no justified live power tweak or driver switch to apply. Installing
and booting the prepared kernel/firmware source requires planned maintenance
coordination with the Telegram supervisor, preserved complete boot payloads
and fresh storage/availability checks. Emergency reset permission is not
reused. A kernel build, exact-source release qualification and the existing
Bolt/Puppet delivery path must precede activation. After boot, verify actual
AER initialization/ownership and HuC initialization, then repeat the bounded
accelerated workflow. Keep the crash cause open unless new evidence actually
identifies it; do not replace that evidence with a long soak or human
certification gate.

## References

- Linux PCI error recovery: https://docs.kernel.org/PCI/pci-error-recovery.html
- i915 unreliable-MMIO diagnostic rationale:
  https://lists.freedesktop.org/archives/dri-devel/2023-March/397308.html
- Existing driver/rollback boundaries: [Falcon Intel Arc](falcon-intel-xe.md).
