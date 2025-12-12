# Nest Configuration

Automation for my personal Linux distribution based on Gentoo

![Nest Screenshot](.screenshot.png)

## Overview

This is a standard [Puppet module](https://www.puppet.com/docs/puppet/latest/modules_fundamentals.html) that provides all the configuration, data, and orchestration needed to build and maintain the [Nest distribution](https://www.joyfullee.me/projects/nest/). It's also a [Bolt project](https://www.puppet.com/docs/bolt/latest/projects.html) for operational support and a [control repo](https://www.puppet.com/docs/pe/latest/control_repo.html) for desired state management.

## Usage

This module defines three main stages to progressively build server and workstation images for OCI containers, VMs, and bare metal systems.

### Supported Platforms

| ISA    | CPU                                                                      | Platform                                                                            |
|--------|--------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| x86-64 | [Haswell](https://en.wikipedia.org/wiki/Haswell_(microarchitecture))     | [Wellsburg](https://en.wikipedia.org/wiki/Intel_X99)                                |
|        | [Zen 5](https://en.wikipedia.org/wiki/Zen_5)                             | [Strix Halo](https://en.wikipedia.org/wiki/Zen_5#Strix_Halo)                        |
| ARM    | [Cortex-A8](https://en.wikipedia.org/wiki/ARM_Cortex-A8)                 | [BeagleBone Black](https://www.beagleboard.org/boards/beaglebone-black)             |
|        |                                                                          | [Raspberry Pi 3](https://www.raspberrypi.com/products/raspberry-pi-3-model-a-plus/) |
| ARM64  | [Cortex-A53](https://en.wikipedia.org/wiki/ARM_Cortex-A53)               | [Pine64](https://pine64.org/)                                                       |
|        |                                                                          | [Radxa Zero](https://wiki.radxa.com/Zero)                                           |
|        |                                                                          | [SOPINE](https://pine64.org/devices/sopine/)                                        |
|        | [Cortex-A72](https://en.wikipedia.org/wiki/ARM_Cortex-A72)               | [Pinebook Pro](https://pine64.org/devices/pinebook_pro/)                            |
|        |                                                                          | [Raspberry Pi 4 / 400](https://www.raspberrypi.com/products/raspberry-pi-400-unit/)   |
|        |                                                                          | [Raspberry Pi 5 / 500](https://www.raspberrypi.com/products/raspberry-pi-500-plus/)   |
|        |                                                                          | [Rock 4](https://wiki.radxa.com/Rock4)                                              |
|        |                                                                          | [Rock 5](https://wiki.radxa.com/Rock5)                                              |
|        |                                                                          | [RockPro64](https://pine64.org/devices/rockpro64/)                                  |
|        |                                                                          | [VMware Fusion](https://en.wikipedia.org/wiki/VMware_Fusion)                        |
| RISC-V | [XuanTie C920](https://www.xrvm.com/product/xuantie/C920)                | [Milk-V Pioneer](https://milkv.io/pioneer)                                          |

Additionally, the module has comprehensive Kubernetes support.

## Related Projects

This configuration works with several other projects that provide data and logistical support for Nest:

### Build

These projects provide pipeline automation and container registries for the OS build:

* [**Stage 0**](https://gitlab.joyfullee.me/nest/stage0): Updated Gentoo Stage 3 images containing Puppet
* [**Stage 1**](https://gitlab.joyfullee.me/nest/stage1): Basic images intended for containers
* [**Stage 2**](https://gitlab.joyfullee.me/nest/stage2): Platform-specific images with kernels
* [**Stage 3**](https://gitlab.joyfullee.me/nest/stage3): Complete images for specific hosts

They use data and plans from this project.

### Portage

These repositories provide package management configuration data:

* [**Gentoo**](https://gitlab.joyfullee.me/nest/gentoo/portage): Snapshot of the Gentoo Portage tree
* [**Haskell**](https://gitlab.joyfullee.me/nest/gentoo/haskell): Snapshot of [the Gentoo Haskell tree](https://github.com/gentoo-haskell/gentoo-haskell)
* [**Overlay**](https://gitlab.joyfullee.me/nest/overlay): Custom ebuilds and profiles

### Tools

* [**CLI**](https://gitlab.joyfullee.me/nest/cli) ([GitHub](https://github.com/jameslikeslinux/nest-cli)): Commands for Nest administration
* [**Dotfiles**](https://gitlab.joyfullee.me/james/dotfiles) ([GitHub](https://github.com/jameslikeslinux/dotfiles)): Dotfiles and other shared home directory things
* [**KubeCM**](https://gitlab.joyfullee.me/james/kubecm) ([GitHub](https://github.com/jameslikeslinux/kubecm)): Orchestration for Kubernetes deployments
