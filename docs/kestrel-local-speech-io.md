# Kestrel local speech I/O

This documents the source-backed speech endpoints prepared for Hermes Agent and
agent-request-broker integration. The services are host-local Podman containers
on `kestrel`; no Kubernetes resources, `.eyrie` service names, or new DNS aliases
are used.

## Runtime selection

- STT: `whisper.cpp` built from source with GGML Vulkan and FFmpeg conversion
  support. The image includes `ggml-large-v3-turbo-q5_0.bin` from
  `ggerganov/whisper.cpp`.
- TTS: `TTS.cpp` built from source, using the Kokoro GGUF CPU path because
  upstream documents Kokoro as CPU/quantization-capable but not Vulkan-capable.
  The image includes `Kokoro_espeak_Q5.gguf` from `mmwillet2/Kokoro_GGUF`.
- Existing kestrel `llama-util` is left source-managed but stopped so the RX 7600
  render device can be used by the STT container.

## Endpoints

- STT health: `http://kestrel:2022/health`
- STT OpenAI-style transcription endpoint:
  `http://kestrel:2022/v1/audio/transcriptions`
- TTS health: `http://kestrel:2023/health` or
  `http://kestrel:2023/v1/health`
- TTS OpenAI-style speech endpoint:
  `http://kestrel:2023/v1/audio/speech`
- TTS voices endpoint: `http://kestrel:2023/v1/audio/voices`

## Future Hermes command-provider shapes

Do not wire these into Hermes profiles until the source branch has been reviewed,
the tool images have been built/published, and kestrel has converged.

STT command provider shape:

```yaml
stt:
  enabled: true
  provider: kestrel-whisper
  providers:
    kestrel-whisper:
      type: command
      command: "curl -fsS -F file=@{input_path} http://kestrel:2022/v1/audio/transcriptions | jq -r .text > {output_path}"
      format: txt
      language: en
      timeout: 300
```

TTS command provider shape:

```yaml
tts:
  provider: kestrel-kokoro
  providers:
    kestrel-kokoro:
      type: command
      command: "jq -Rs --arg voice '{voice}' --arg format wav '{input: ., voice: $voice, response_format: $format}' {input_path} | curl -fsS -H 'Content-Type: application/json' -d @- http://kestrel:2023/v1/audio/speech > {output_path}"
      output_format: wav
      voice: af_heart
      voice_compatible: true
      timeout: 120
```

## Source surfaces

- Build classes: `nest::tool::whispercpp`, `nest::tool::ttscpp`
- Build Hiera: `data/build/Gentoo/whisper.cpp/whisper.cpp.yaml`,
  `data/build/Gentoo/tts.cpp/tts.cpp.yaml`
- Host service classes: `nest::service::speech_io`, `nest::lib::whisper_server`,
  `nest::lib::tts_server`
- Kestrel Hiera: `data/host/kestrel.yaml`

## Review/rollout gates

1. Create/push the companion GitLab CI wrapper projects for `nest/tools/whisper.cpp`
   and `nest/tools/tts.cpp` using the same `gitlab-ci.yml` shape as
   `nest/tools/llama.cpp`.
2. Run the sifive-u74 tool-image pipelines and publish
   `registry.gitlab.joyfullee.me/nest/tools/whisper.cpp:sifive-u74` and
   `registry.gitlab.joyfullee.me/nest/tools/tts.cpp:sifive-u74` plus their
   manifest tags.
3. Deploy Puppet source, converge `kestrel` twice, and verify:
   - `container-whisper-whisper` active on port 2022
   - `container-tts-kokoro` active on port 2023
   - `container-llama-util` stopped/disabled
   - `/dev/dri/renderD128` visible to the whisper container
   - real transcription and speech synthesis requests return expected text/audio
