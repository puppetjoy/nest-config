# Owl/Eyrie local voice I/O design

## Live target evidence

Captured on owl during the redesign:

- Host: `owl`, Linux 6.18.21, x86_64 AMD Ryzen AI MAX+ 395 with Radeon 8060S.
- GPU visibility after the managed ROCm reboot: `amdgpu` is loaded,
  `/dev/dri/renderD128` and `/dev/kfd` exist, and `rocminfo` enumerates
  `gfx1151` / Radeon 8060S Graphics.
- Kernel config after the managed build/reboot includes
  `CONFIG_DRM_AMDGPU_USERPTR=y`, `CONFIG_HSA_AMD=y`, and
  `CONFIG_HSA_AMD_SVM=y`.
- ROCm userspace on owl includes `dev-util/hip-7.2.0-r1`,
  `dev-util/hipcc-7.2.0`, and `dev-util/rocminfo-7.2.0`.
- Strix Halo memory is exposed as shared GTT: about 120 GiB total; with
  `llama-qwen` loaded, the Qwen pod remained `Ready` on owl.
- Eyrie advertises `squat.ai/gpu: 3` on owl; `llama-qwen` requests one GPU and
  is the coexistence baseline. The generic device plugin must project both
  `/dev/dri/renderD128` and `/dev/kfd` for ROCm pods.

## Immediate ROCm/HIP enablement

Joy's review direction is to skip the Speaches CPU bootstrap and go straight to
enabling ROCm on owl. The source-of-truth changes are therefore host/platform
enablement first, not a CPU speech workload:

- `data/platform/strix-halo.yaml` enables:
  - `CONFIG_HSA_AMD=y` for the AMD KFD/HSA kernel driver and `/dev/kfd`.
  - `CONFIG_HSA_AMD_SVM=y`, `CONFIG_MEMORY_HOTPLUG=y`,
    `CONFIG_MEMORY_HOTREMOVE=y`, `CONFIG_ZONE_DEVICE=y`, and
    `CONFIG_DEVICE_PRIVATE=y` so HIP unified/shared memory support can be
    selected by the kernel.
- `data/host/owl.yaml` adds `nest::service::rocm` and host-scoped `~amd64`
  keyword acceptance for the ROCm 7.2 / LLVM 22 package graph observed by
  `emerge -pv --autounmask-only dev-util/rocminfo dev-util/hip dev-util/hipcc`.
- `manifests/service/rocm.pp` installs `dev-util/rocminfo`, `dev-util/hip`, and
  `dev-util/hipcc`, and makes the opted-in host select `amdgpu radeonsi` Portage
  video cards.

Rollout behavior proven in the accepted deployment:

1. Puppet deployed the source and converged on owl.
2. ROCm/HIP 7.2 packages were built/installed.
3. The Strix Halo kernel config required a managed kernel build/install and an
   approved reboot before `/dev/kfd` appeared.
4. After reboot, `rocminfo` enumerated the Radeon 8060S as `gfx1151`; if a future
   kernel loses this state, inspect `dmesg` for `kfd`/`amdgpu` rejection details
   before changing a KubeCM speech workload.

## Runtime choice after ROCm works

The first accepted speech service should be ROCm-backed and OpenAI-compatible,
not a CPU-only proof of health.

- TTS: Kokoro-FastAPI is the preferred first TTS runtime because it is a
  Kokoro-82M FastAPI service with an OpenAI-compatible `/v1/audio/speech` route,
  and current source survey found ROCm-oriented Strix Halo work around that
  runtime. The stock public `ghcr.io/remsky/kokoro-fastapi-rocm:latest` image is
  not suitable for owl as-is: it currently carries ROCm 6.4 / PyTorch
  `2.8.0+rocm6.4`, sees the GPU, but fails real kernels on `gfx1151`. Build a
  Nest tool image with ROCm 7.2 and AMD `repo.radeon.com` PyTorch wheels for
  `gfx1151`; set `MIOPEN_FIND_MODE=2` and persist the MIOpen/model cache on an
  `owl-crypt` PVC rather than falling back to TTS.cpp.
- STT: use a PyTorch ROCm Whisper-family service first. OpenAI Whisper has a
  native PyTorch execution path that can use ROCm once `torch` sees HIP, and a
  thin FastAPI wrapper can expose `/v1/audio/transcriptions` if the selected
  runtime does not. Faster-whisper/WhisperX can be revisited after ROCm is live,
  but do not choose a CTranslate2 path unless the ROCm backend is proven on owl.

## KubeCM service gate

Only add or deploy the Eyrie speech KubeCM service after the host gate passes:

1. `/dev/kfd` and `/dev/dri/renderD128` exist on owl.
2. `rocminfo` or an equivalent HIP probe enumerates the Radeon 8060S.
3. A test pod scheduled to owl with `squat.ai/gpu: 1` can see the KFD/DRI devices
   and run a HIP/PyTorch probe.
4. The selected runtime returns a real audio file from `POST /v1/audio/speech`.
5. The selected STT route returns a real transcript from
   `POST /v1/audio/transcriptions`.
6. `llama-qwen` stays `Ready` with no new restarts before and after the voice
   probes.

The service should live in namespace `ai`, schedule on owl, request
`squat.ai/gpu`, use `owl-crypt` for persistent model/cache storage when needed,
and preserve the same private-cluster HTTP integration style used by the existing
`llama-qwen` service.
