# Retired Kestrel local speech I/O

Kestrel is no longer the Nest speech I/O target. The previous Podman speech
prototype used `whisper.cpp` on port 2022 and `TTS.cpp`/Kokoro on port 2023,
but that design is retired for two reasons:

- `TTS.cpp` on Linux/RISC-V exposed CPU/thread and Metal-oriented controls, not
  a deployable Vulkan/ROCm/HIP path for Kestrel's Radeon RX 7600. CPU synthesis
  was too slow for Joy's Hermes voice loop.
- Joy wants speech I/O modeled like the Eyrie `llama-qwen` service: Kubernetes
  source under `data/kubernetes`, deployment plans under `plans/eyrie/ai`, and
  owl/Strix Halo as the local accelerator target.

Source cleanup in this repo therefore removes the Kestrel
`nest::service::speech_io` Hiera instances and drops the retired speech tool-image
sources, including the old `whisper.cpp` STT image and `TTS.cpp` TTS image. After
the Puppet source is deployed and Kestrel has converged, the old Puppet-managed
containers become approved orphaned artifacts to stop/disable and remove manually:

- `container-whisper-whisper.service` / `whisper-whisper`
- `container-tts-kokoro.service` / `tts-kokoro`
- ports 2022 and 2023

Historical note: the retired Kestrel prototype used `whisper.cpp` for STT before
speech I/O moved to the Eyrie `voice-speech` service. The current STT path uses
OpenAI Whisper inside a ROCm/PyTorch Kubernetes workload instead of the retired
`nest/tools/whisper.cpp` image.

## Replacement direction

There is intentionally no CPU bootstrap service. Joy's review direction was to
skip Speaches and go straight to enabling ROCm on owl, so this branch removes the
prototype Speaches KubeCM app/plan and first makes owl a real ROCm/HIP-capable
host:

- `data/platform/strix-halo.yaml` enables the AMD KFD/HSA kernel options that
  create `/dev/kfd`.
- `data/host/owl.yaml` includes `nest::service::rocm` and accepts the Gentoo
  `~amd64` ROCm 7.2 / LLVM 22 package stack needed by `dev-util/rocminfo`,
  `dev-util/hip`, and `dev-util/hipcc`.
- `manifests/service/rocm.pp` installs those ROCm/HIP userland packages and
  selects `amdgpu radeonsi` video cards for the opted-in host.

The host gate now passes after the approved owl reboot: `/dev/kfd` exists,
`rocminfo` enumerates the Radeon 8060S as `gfx1151`, and Kubernetes GPU pods can
see both `/dev/kfd` and `/dev/dri/renderD128` while requesting the existing
`squat.ai/gpu` resource. The remaining runtime gate is a speech image built
against ROCm/PyTorch versions that actually support `gfx1151`.

## Candidate runtime shape after ROCm is live

- TTS: start with Kokoro-FastAPI, but build a Nest ROCm 7.2 / PyTorch 2.10+
  image for `gfx1151` under the normal Nest tool-image workflow rather than using
  the current public ROCm 6.4 image. Kokoro-FastAPI exposes the
  OpenAI-compatible `POST /v1/audio/speech` route needed by Hermes command
  providers.
- STT: start with a PyTorch ROCm Whisper service using OpenAI Whisper or
  WhisperX-style code, then wrap it with `POST /v1/audio/transcriptions` if the
  selected runtime does not already expose that route.
- Integration: keep Hermes on command providers that call private Eyrie HTTP
  endpoints; do not patch Hermes source for file-in/file-out speech calls.

Do not deploy a KubeCM speech service that only proves CPU health. The next
source-backed service should request `squat.ai/gpu`, schedule on owl, use an
`owl-crypt` cache/model PVC if persistent storage is needed, and prove real TTS
audio plus real STT transcription through live OpenAI-style routes while
`llama-qwen` remains Ready.
