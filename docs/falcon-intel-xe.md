# Falcon Intel Arc driver selection

## Durable ownership

Wellsburg enables the Xe module as a platform capability. It does not force
experimental probing of every Intel PCI device. Falcon's host kernel command
line selects its Arc A750 (`8086:56a1`) explicitly:

```text
i915.force_probe=!56a1 xe.force_probe=56a1
```

Both parameters are required: Falcon's i915 driver is built in and can bind the
Arc before the Xe module loads. Enabling `CONFIG_DRM_XE=m`, or setting its
force-probe default, does not displace an already-bound i915 device. These
command-line parameters override the compiled defaults, including the wildcard
in the currently installed kernel. A future Wellsburg kernel build uses an
empty default rather than a platform-wide experimental wildcard. A kernel
recompile is not required to apply the host's explicit boot selection.

Keep the existing IOMMU, CPU isolation and `pci-stub.ids` configuration. The
NVIDIA GPU, its audio function and the guest USB controller remain assigned to
VFIO; this repair does not change guest devices or PCI topology.

## Firmware and feature boundaries

Inspect the actual boot initramfs, not only the mounted firmware directory.
The pre-repair 6.18.56 initramfs contains Xe, DG2 GuC and DG2 DMC. The installed
Xe module declares those DG2 firmware dependencies. Verify them again in the
selected artifact after managed `kernel-install`/dracut regeneration.

The old initramfs lacks `i915/dg2_huc_gsc.bin`, although that file exists in the
mounted root. This explains how a boot can report missing firmware that is
present later; it does not establish when the omission first occurred.
The installed kernel's `drivers/gpu/drm/xe/xe_uc_fw.c` explicitly says DG2 HuC
is not supported by Xe. Do not claim that copying the HuC file enables that
feature under Xe. Verify actual VA-API, Firefox and Plex behavior, including
the applicable HDR path, instead of treating firmware presence or capability
advertisements as functional acceptance. BAR resizing previously failed and
fell back to 256 MiB; changing BIOS or PCI topology is not part of this repair.

The profile-driven iHD provider is owned by overlay MR !14 and request ^2316.
Do not duplicate that package policy in Falcon's Puppet class.

## Maintenance and rollback

Source review, exact-head CI and owner source approval precede live delivery.
Deploy accepted source with the repository's Bolt/Puppet plans. Inspect the
rendered `/etc/kernel/cmdline`, selected loader entry, kernel/module identities
and initramfs dependencies. Preserve the original loader entry and its complete
kernel/initramfs payload separately before same-version regeneration; an old
BE alone does not protect the shared ESP from artifact replacement. Preserve
inactive BE A and the current BE's data. Do not delete rollback state for space.

Falcon's ordinary reboot/shutdown path has a separate known deadlock, tracked
in work item 85. Only the explicitly authorized Falcon SysRq reset is allowed
for this maintenance. SysRq `b` performs no shutdown, sync or unmount itself.
Keep control independent of Falcon, notify before the reset, quiesce guests,
CI, backups, applications and storage writers through bounded supported paths,
and verify successful flushing and completed installation/copy operations.

Check Ceph quorum, PG state, replica/shard placement and `ceph osd ok-to-stop`
for **all** Falcon OSDs together. A refusal must be understood and resolved in
the maintenance preparation, not ignored because the host is Node Ready or
because service interruption was authorized. In particular, a pool that loses
availability needs all of its consumers quiesced and a proven clean storage
stop; never lower `min_size`, disable durability or delete storage to pass a
gate. A hung flush or unknown write state forbids the reset.

After return, require a changed boot ID, the selected BE/kernel and actual
`0000:05:00.0/driver -> xe`, matching DRM render-device identity, firmware
initialization and real host/browser/Plex accelerated workloads. Check guests,
Kubernetes volumes, Ceph, GitLab/Runner, media/public Ombi, networking and system
and user units. Physical audiovisual quality remains unverified unless someone
actually observes it. Keep pre-existing warnings separate from new failures.

## Historical evidence

Commit `8226a94af821032e866bbc9a8d8ec4934a70a5e7` records Xe intent. Retained
October boots already used i915; neither that intent nor the October kernel
update identifies a verified last-good/first-bad transition. Do not attribute
historical driver loss to that update without new causal evidence.
