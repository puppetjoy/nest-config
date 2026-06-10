# Owl Chatterbox activation path

This branch adds a managed Chatterbox-Turbo candidate service for the accepted
Talon and Star generated-reference presets. The service is separate from the
stable `voice-speech` Kokoro/Whisper service so a Chatterbox rollout cannot
accidentally contaminate the current local speech baseline.

## Managed service

- KubeCM app: `data/kubernetes/app/voice-chatterbox.yaml`
- KubeCM service data: `data/kubernetes/service/voice-chatterbox.yaml`
- Deploy plan: `nest::eyrie::ai::deploy_voice_chatterbox`
- Namespace: `ai`
- Kubernetes service: `voice-chatterbox`
- Runtime base: `docker.io/rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1`
- Chatterbox source: `resemble-ai/chatterbox` at
  `3f35dfc8fbe63e5b29793289dc68f1875bb317a5`

The pod installs Chatterbox with `--no-deps`, then installs the runtime
libraries separately. This preserves the ROCm PyTorch stack from the base image
instead of allowing upstream Chatterbox metadata to replace it with pinned
`torch==2.6.0` / `torchaudio==2.6.0` wheels. Startup asserts that the live torch
version is still the ROCm 7.2.4 build before serving requests.

The accepted generated-reference preset manifest and WAVs are mounted as
Kubernetes ConfigMaps:

- `voice-chatterbox-presets`
- `voice-chatterbox-talon-reference`
- `voice-chatterbox-star-reference`

The reference WAV SHA256s are checked on `/health` and before every speech
request.

## Endpoint boundary

The service exposes private OpenAI-compatible-enough routes for the next rollout
verification step:

- `GET /health`
- `GET /v1/models`
- `GET /v1/audio/voices`
- `POST /v1/audio/speech`

Only the reviewed preset names are active initially:

- `talon-elegant`
- `star-clear`

The short aliases `talon` and `star` remain inactive. The API reports them as
`aliases_pending_final_approval` and returns HTTP 409 if a caller tries to use
one before the final provider-switch approval.

## Verification still required before profile activation

After review/merge, deploy the candidate service through the managed plan and
collect live evidence before changing Talon or Star production TTS settings:

1. `bolt plan run nest::eyrie::ai::deploy_voice_chatterbox`
2. `kubectl -n ai get pod,svc -l app=voice-chatterbox -o wide`
3. `curl -fsS http://<cluster-ip>/health`
4. Generate one `/v1/audio/speech` WAV for `talon-elegant` and one for
   `star-clear`.
5. Inspect each WAV with `ffprobe` and record duration, sample rate, channels,
   SHA256, wall time, and real-time factor from the response headers.
6. Run at least one STT clarity round trip against the existing `voice-speech`
   transcription endpoint using Nest operational vocabulary.
7. Capture resource evidence from pod readiness/restarts and available GPU/GTT
   tooling.

Only after that evidence is acceptable should a separate trusted approval switch
Talon/Star production TTS providers or activate the short aliases.
