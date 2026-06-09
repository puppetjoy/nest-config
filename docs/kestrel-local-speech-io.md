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
`nest::service::speech_io` Hiera instances and drops the `TTS.cpp` tool-image
source. After the Puppet source is deployed and Kestrel has converged, the old
Puppet-managed containers become approved orphaned artifacts to stop/disable and
remove manually:

- `container-whisper-whisper.service` / `whisper-whisper`
- `container-tts-kokoro.service` / `tts-kokoro`
- ports 2022 and 2023

`whisper.cpp` remains in source only as a useful C/C++ Whisper runtime for future
non-RISC-V/Vulkan work. Do not rebuild the RISC-V `sifive-u74` speech images for
this retirement.

## Replacement design

The replacement is `voice-speech` in namespace `ai`, backed by the KubeCM app
`data/kubernetes/app/speaches.yaml`, service data
`data/kubernetes/service/voice-speech.yaml`, and deployment plan
`plans/eyrie/ai/deploy_voice_speech.yaml`. It exposes OpenAI-style endpoints for
Hermes command providers:

```yaml
stt:
  enabled: true
  provider: eyrie-voice
  providers:
    eyrie-voice:
      type: command
      command: "curl -fsS -F file=@{input_path} -F model=Systran/faster-distil-whisper-small.en http://voice-speech.ai/v1/audio/transcriptions | jq -r .text > {output_path}"
      format: txt
      timeout: 300

tts:
  provider: eyrie-voice
  providers:
    eyrie-voice:
      type: command
      command: "jq -Rs --arg model speaches-ai/Kokoro-82M-v1.0-ONNX --arg voice af_heart --arg format wav '{input: ., model: $model, voice: $voice, response_format: $format}' {input_path} | curl -fsS -H 'Content-Type: application/json' -d @- http://voice-speech.ai/v1/audio/speech > {output_path}"
      output_format: wav
      voice: af_heart
      voice_compatible: true
      timeout: 300
```

The first source-backed deployment uses Speaches' CPU image on owl with an
`owl-crypt` model cache PVC. This is intentionally a bootstrap/prototype: live
owl evidence on 2026-06-09 shows `amdgpu` and `/dev/dri/renderD128`, but no
`/dev/kfd` and no ROCm/HIP userland tools, so Kubernetes cannot yet run the
preferred ROCm/HIP path. Once Puppet enables `/dev/kfd` and ROCm/HIP packages,
retarget the app to an AMD/ROCm image and add `squat.ai/gpu` requests/limits
using the same resource pattern as `llama-qwen`.
