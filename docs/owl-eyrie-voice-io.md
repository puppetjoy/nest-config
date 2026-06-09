# Owl/Eyrie local voice I/O design

## Live target evidence

Captured on owl during the redesign:

- Host: `owl`, Linux 6.18.21, x86_64 AMD Ryzen AI MAX+ 395 with Radeon 8060S.
- GPU visibility: `amdgpu` is loaded and `/dev/dri/renderD128` exists.
- HIP blocker: `/dev/kfd` is absent and `rocminfo`/`hipcc`/`rocm-smi` are not
  installed in the host tool environment.
- Strix Halo memory is exposed as shared GTT: about 120 GiB total; with
  `llama-qwen` loaded, roughly 90 GiB was in use and the Qwen pod remained
  `Ready` on owl.
- Eyrie advertises `squat.ai/gpu: 3` on owl; `llama-qwen` requests one GPU and
  is the coexistence baseline.

## Runtime choice

Use Speaches as the first Eyrie speech API because it is OpenAI-compatible for
both required routes:

- STT: `/v1/audio/transcriptions`, powered by `faster-whisper`. The
  `faster-whisper` package describes a CTranslate2 Whisper implementation that
  is up to 4x faster than OpenAI Whisper for the same accuracy and supports
  lower-memory int8 modes.
- TTS: `/v1/audio/speech`, using Kokoro/Piper. Speaches documents
  `speaches-ai/Kokoro-82M-v1.0-ONNX` and voice `af_heart` for OpenAI-style
  speech synthesis. Kokoro-82M is small enough to coexist with Qwen and is
  Apache-licensed/open-weight.

Alternative TTS candidate: `remsky/Kokoro-FastAPI` is a dedicated Kokoro API
with CPU, NVIDIA, and experimental x86_64 ROCm images and OpenAI-compatible
`/v1/audio/speech`. It is the likely fallback if Speaches' combined service is
not reliable enough, but it would require a second STT service or a thin routing
wrapper.

Rejected target: `TTS.cpp` on Kestrel. Live help output and upstream docs showed
no deployable Linux Vulkan/ROCm/HIP acceleration path; keeping it would continue
the failed CPU-bound architecture.

## Source-backed deployment

KubeCM source:

- App: `data/kubernetes/app/speaches.yaml`
- Service data: `data/kubernetes/service/voice-speech.yaml`
- Deploy plan: `plans/eyrie/ai/deploy_voice_speech.yaml`
- Namespace: `ai`
- Node/storage: pinned to owl with `owl-crypt` PVC cache

The bootstrap image is the linux/amd64 digest of
`ghcr.io/speaches-ai/speaches:latest-cpu`, captured as
`sha256:1d4f852ff5b148d675bcd751f414835c0bcef2541c1df8ffdeb43714968aafe6`.
It intentionally does not request `squat.ai/gpu` until `/dev/kfd` and HIP are
available to containers. This avoids reserving a GPU for a CPU-only image while
keeping the workload on owl and preserving the exact point where the ROCm path
will change.

## ROCm/HIP enablement plan

Before switching to a GPU image, express host enablement through Nest
Puppet/Bolt source and verify after an explicit reboot window if kernel config
or device-node changes require one:

1. Host has `/dev/kfd` and `/dev/dri/renderD128`.
2. Host ROCm/HIP userland tools (`rocminfo` or equivalent) can enumerate the
   Radeon 8060S.
3. Kubernetes pods can see the same devices with the generic device plugin.
4. A Speaches/Kokoro ROCm image or a dedicated Kokoro-FastAPI ROCm image
   generates real audio.
5. Add `squat.ai/gpu: '1'` requests/limits to the speech pod and size it so
   `llama-qwen` keeps one GPU allocation and its 120 Gi memory ceiling.

## Verification gates

The service is not accepted merely because the pod is healthy. Prove both real
paths:

1. Generate a short WAV through `POST /v1/audio/speech` with
   `speaches-ai/Kokoro-82M-v1.0-ONNX` and `af_heart`; verify the result is an
   audio file.
2. Feed that generated WAV back to `POST /v1/audio/transcriptions` with
   `Systran/faster-distil-whisper-small.en`; verify the transcript contains the
   prompt text.
3. Check `llama-qwen` remains `Ready`, with no new restarts, before and after
   speech generation.
