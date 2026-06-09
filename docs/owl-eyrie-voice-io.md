# Owl/Eyrie local voice I/O design

## Live target evidence

Captured on owl during the redesign:

- Host: `owl`, Linux 6.18.21, x86_64 AMD Ryzen AI MAX+ 395 with Radeon 8060S.
- GPU visibility: `amdgpu` is loaded and `/dev/dri/renderD128` exists.
- HIP blocker before this source change: `/dev/kfd` is absent because the live
  kernel has `# CONFIG_HSA_AMD is not set`; `rocminfo`/`hipcc`/`rocm-smi` are not
  installed in the host tool environment.
- Strix Halo memory is exposed as shared GTT: about 120 GiB total; with
  `llama-qwen` loaded, roughly 90 GiB was in use and the Qwen pod remained
  `Ready` on owl.
- Eyrie advertises `squat.ai/gpu: 3` on owl; `llama-qwen` requests one GPU and
  is the coexistence baseline.

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

Expected apply behavior:

1. Puppet deploys the source and applies on owl.
2. ROCm/HIP packages may be built/installed.
3. Kernel config changes require a managed kernel build/install and an explicit
   scheduled reboot before `/dev/kfd` can appear.
4. After the reboot, `rocminfo` should enumerate the Radeon 8060S; if it does
   not, inspect `dmesg` for `kfd`/`amdgpu` rejection details before adding a
   KubeCM speech workload.

## Runtime choice after ROCm works

The first accepted speech service should be ROCm-backed and OpenAI-compatible,
not a CPU-only proof of health.

- TTS: Kokoro-FastAPI is the preferred first TTS runtime because it is a
  Kokoro-82M FastAPI service with an OpenAI-compatible `/v1/audio/speech` route,
  and current source survey found ROCm-oriented Strix Halo work around that
  runtime. If the public image is not suitable for Eyrie, build a Nest tool image
  with ROCm PyTorch and Kokoro-FastAPI rather than falling back to TTS.cpp.
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
