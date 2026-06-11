# Current Nest speech stack

This document is the canonical steady-state reference for Joy's current local
speech I/O path. Older documents remain useful history, but this file describes
what is in production now and which experiments are retired.

## Production architecture

Talon and Star use the private Eyrie `voice-speech` service for both STT and
TTS through Hermes command providers. The service runs in the Kubernetes `ai`
namespace as `voice-speech`, is private to the cluster, and is currently pinned
to owl. It uses ROCm PyTorch on the Strix Halo GPU, Kokoro for TTS, and OpenAI
Whisper for STT.

The boundary is intentionally thin:

1. Hermes receives Telegram voice/audio input and calls the configured STT
   command provider.
2. `/opt/hermes-agent/bin/hermes-voice-speech-stt` posts the audio to
   `voice-speech` `/v1/audio/transcriptions`.
3. Hermes direct voice replies call the configured TTS command provider.
4. `/opt/hermes-agent/bin/hermes-voice-speech-tts` posts normalized speech text
   to `voice-speech` `/v1/audio/speech` and writes the returned WAV.
5. Hermes handles Telegram voice-compatible conversion and delivery when the
   output should be sent as a native voice note.
6. agent-request-broker notification sidecar audio invokes Hermes TTS under the
   target profile, so the same profile config and `voice-speech` provider are
   used for Talon/Star notifications.

Current source owners:

- Nest KubeCM service: `data/kubernetes/app/voice-speech.yaml` and
  `data/kubernetes/service/voice-speech.yaml`
- Deployment plan: `plans/eyrie/ai/deploy_voice_speech.yaml`
- Profile settings: `data/host/owl.yaml`
- Hermes profile rendering: `manifests/lib/hermes.pp`
- Hermes wrapper deployment: `manifests/app/hermes/service.pp`
- TTS wrapper: `files/app/hermes/voice-speech-tts-command.py`
- STT wrapper: `files/app/hermes/voice-speech-stt-command.py`
- Nest-side normalization corpus:
  `files/app/hermes/voice-speech-normalization-corpus.json`

## Profile settings

The production Talon and Star profile settings are rendered from
`data/host/owl.yaml`.

Shared defaults:

- `voice_auto_tts: true`
- `stt_provider: voice-speech`
- `stt_voice_speech_endpoint: http://10.108.246.221`
- `stt_voice_speech_model: whisper-large-v3-turbo`
- `tts_provider: voice-speech`
- `tts_voice_speech_endpoint: http://10.108.246.221`
- `tts_voice_speech_model: kokoro`
- `tts_voice_speech_format: wav`
- `tts_voice_compatible: true`
- `AGENT_REQUEST_TELEGRAM_VOICE_NOTIFY=true` when profile voice auto-TTS is
  enabled

Profile voice choices:

- Talon: `af_alloy`
- Star: `af_nova`

The shared STT initial prompt includes local operational vocabulary such as
Talon, Star, Honcho, Eyrie, KubeCM, llama-qwen, GitLab, Puppet, Kubernetes,
OpenVox, ROCm, kubectl, owl, voice-speech, and Kokoro.

## Speech-normalization policy

Speech normalization is speech-only. It must not mutate the visible Telegram or
Markdown notification text.

Retained behavior:

- Suppress low-value Agent Request ids, task ids, review acceptance ids,
  checksums, hashes, and long commit identifiers.
- Shorten URLs and filesystem paths so audio gives useful location words rather
  than slash-heavy literals.
- Preserve exact/verbatim escapes for text Joy explicitly wants spoken without
  operational shortening.
- Keep operational proper nouns pronounceable in the Nest direct-call wrapper
  and service fallback: KubeCM, Eyrie, kubectl, llama-qwen, OpenVox, and ROCm.
- Keep command-provider integration as the production boundary.

Rejected behavior:

- Do not reintroduce dash insertion as an active cadence policy.
- Do not reintroduce Joy-opening clip stitching, onset padding, stretch, or
  post-audio pause surgery.
- Do not read full hashes/checksums/request ids by default.
- Do not treat STT transcript correctness as proof that punctuation cadence is
  natural; waveform/listening evidence is required for future cadence work.

The current Nest wrapper and service-side `/v1/audio/normalize` implementations
are fallback safety nets. Hermes direct TTS and agent-request-broker have their
own normalization paths today, so the long-term guardrail is a shared behavior
corpus mirrored across repos rather than independent ad-hoc fixes.

## Acceptance checks

Before reporting a speech-stack source change ready for review, collect the
checks that apply to the changed surface.

Source checks:

- `python3 -m py_compile files/app/hermes/voice-speech-tts-command.py \
  files/app/hermes/voice-speech-stt-command.py \
  files/app/hermes/voice-speech-normalization-regression.py`
- `files/app/hermes/voice-speech-normalization-regression.py`
- `python3 - <<'PY'` YAML parse checks for edited KubeCM Hiera files if PDK is
  not being run for the review boundary.
- `pdk validate` only when explicitly requested or when preparing the normal
  repo validation gate.

Live checks after reviewed deployment:

- `/health` returns `ok: true` and the expected app version.
- `/v1/audio/voices` contains Talon and Star voices: `af_alloy` and `af_nova`.
- A TTS request returns non-empty WAV audio with useful duration, sample rate,
  non-silence, and acceptable real-time factor.
- STT transcribes the generated WAV with the expected smoke words present.
- `ai/voice-speech` pod restart count has not increased unexpectedly.
- Live `/health` version matches the source-managed expected version.

Deployment commands after review acceptance:

- Deploy KubeCM source with `bolt plan run nest::eyrie::ai::deploy_voice_speech`
  or the repo's current wrapper for `plans/eyrie/ai/deploy_voice_speech.yaml`.
- Apply Puppet on owl when profile config or wrapper installation changes.
- Restart Talon/Star gateways only when rendered profile config, env, wrappers,
  or Hermes/broker code changes require it.

## Historical or retired materials

The following are history unless Joy explicitly revives them:

- Chatterbox-generated reference voices and Chatterbox production tuning notes.
- Codex/OpenAI speech-provider experiments and managed OpenAI STT/TTS defaults.
- Kestrel whisper.cpp/TTS.cpp Podman/Vulkan exploration.
- Dash-cadence samples from earlier Kokoro punctuation experiments.
- Joy-opening clip stitching, stretch, onset-padding, and post-audio surgery.

Related historical docs remain useful for context:

- `docs/owl-eyrie-voice-io.md`
- `docs/owl-voice-speech-tts-bakeoff.md`
- `docs/kestrel-local-speech-io.md`

When future agents read those docs, they should treat this file as the active
production posture and treat the older material as incident/evaluation history.

## Upstream boundary

Potentially upstreamable Hermes work must avoid Joy/Nest-specific strings:

- Generic command STT/TTS providers and voice-compatible command output.
- Generic technical-token, path, URL, hash, checksum, and request-id speech
  normalization with an exact/verbatim escape hatch.
- Generic Telegram voice-note media routing and Opus conversion behavior.

Nest-local details should stay local:

- The `voice-speech` service implementation, endpoint, KubeCM deployment, owl
  placement, and ROCm/Kokoro/Whisper cache details.
- Talon/Star voice choices.
- Joy opener and Agent Request notification phrasing.
- Operational vocabulary such as KubeCM, Eyrie, OpenVox, ROCm, Talon, Star, and
  Honcho.
