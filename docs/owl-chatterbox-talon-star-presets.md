# Owl Chatterbox Talon/Star candidate presets

## Scope

Joy chose the generated-reference Chatterbox candidates by ear from the
`ar-20260610-071520-ea6b74` voice grid:

- Talon: source candidate `star-alloy-elegant`, candidate preset `talon-elegant`
- Star: source candidate `star-nova-clear`, candidate preset `star-clear`

This branch source-manages those chosen generated references and preset metadata
for a future local Chatterbox candidate service. It does not change the Talon or
Star production TTS providers and does not add the short aliases `talon` or
`star`; those aliases should wait for explicit final approval after listening
review.

## Source-managed preset assets

Preset metadata lives at:

`files/app/voice-speech/chatterbox-presets/presets.json`

The selected generated-reference WAVs are small enough to keep with the Nest
source of truth for now:

| Candidate preset | Persona | Source candidate | Reference path | SHA256 |
| --- | --- | --- | --- | --- |
| `talon-elegant` | Talon | `star-alloy-elegant` | `files/app/voice-speech/chatterbox-presets/talon-elegant/reference.wav` | `41a7d95035c73b5c77de3af38c9b74fef11a3aac32a5b3dcdbebad949db1f600` |
| `star-clear` | Star | `star-nova-clear` | `files/app/voice-speech/chatterbox-presets/star-clear/reference.wav` | `40faa648c03da6dc1fd466d1d9dd3178ae88acf21107d6b24926dc3e8391360d` |

The references came from the generated-reference route only; no user-provided
recordings were requested or used. The original review grid remains at:

`/home/joy/projects/.worktrees/hermes-agent/t_b09f8cd2/artifacts/chatterbox-voice-grid-20260610T071928Z`

## Acceptance pack

A final two-voice acceptance pack was generated under this task workspace:

`artifacts/chatterbox-acceptance-20260610T074721Z/generated`

It contains four normalized/professional prompts for each preset:

- `notification`
- `ops_update`
- `persona`
- `style_probe`

Generation used the live owl `ai/voice-speech` ROCm PyTorch environment as a
temporary evaluation path, with Chatterbox dependencies installed under `/tmp`
only. The deployed `voice-speech` startup config and Talon/Star production TTS
providers were not changed.

Runtime evidence from the acceptance manifest:

- Chatterbox-Turbo model: `ResembleAI/chatterbox-turbo` via the upstream
  `resemble-ai/chatterbox` code path.
- Torch: `2.9.1+rocm7.2.4.git39497456`
- HIP: `7.2.53211-97f5574fe2`
- GPU: `Radeon 8060S Graphics`
- Reference normalization: `norm_loudness=False`, preserving the known ROCm
  workaround for Chatterbox's float64 reference-audio path.
- Model load: `2.576s`

Acceptance generation timings:

| Preset | Sample | Audio seconds | Wall seconds | RTF |
| --- | --- | ---: | ---: | ---: |
| `talon-elegant` | notification | 10.24 | 18.852 | 1.841 |
| `talon-elegant` | ops_update | 11.32 | 10.595 | 0.936 |
| `talon-elegant` | persona | 10.12 | 9.339 | 0.923 |
| `talon-elegant` | style_probe | 7.36 | 6.897 | 0.937 |
| `star-clear` | notification | 10.08 | 9.533 | 0.946 |
| `star-clear` | ops_update | 8.72 | 8.162 | 0.936 |
| `star-clear` | persona | 11.64 | 10.607 | 0.911 |
| `star-clear` | style_probe | 9.16 | 8.442 | 0.922 |

The first sample after model load was slower, but warm samples stayed near
realtime. This is acceptable for review artifact generation; production use still
needs a real sibling service/image and latency review before any provider switch.

## STT round-trip results

The acceptance WAVs were transcribed through the current private
`voice-speech` endpoint:

- Endpoint: `http://10.108.246.221/v1/audio/transcriptions`
- Model: `small`
- Language: `en`
- Temperature: `0.0`
- `condition_on_previous_text=false`
- Initial prompt:
  `Talon Star Honcho Eyrie KubeCM llama-qwen GitLab Puppet Kubernetes OpenVox ROCm kubectl owl voice-speech Chatterbox Kokoro`

Observed transcripts:

| Preset | Sample | Transcript |
| --- | --- | --- |
| `talon-elegant` | notification | Talon has a review-ready update. The Chatterbox candidate pack is complete. The selected references are source-managed and production TS remains unchanged. |
| `talon-elegant` | ops_update | Status, KubeCtrl in namespace AI reports deploy voice-speech ready. The health endpoint is green, the manifest is saved, and Joy can review the audio before any provider switch. |
| `talon-elegant` | persona | I am Talon, a small watchful owl at a laptop. I keep the thread focused, name the evidence and explain the next safe step for joy without rushing. |
| `talon-elegant` | style_probe | Tiny owl checkpoint. The fix is source managed, the live service is untouched, and the next move waits for approval. |
| `star-clear` | notification | Star has a clear review update. The chosen Chatterbox voice is packaged as a candidate preset. Artifacts are ready and Talon and Star production voices are unchanged. |
| `star-clear` | ops_update | Status The local voice-speech service is ready on owl. Whisper Large B3 Turbo can transcribe the acceptance samples with the Nest Vocabulary Prompt. |
| `star-clear` | persona | I am star, bright, careful, and easy to follow. I can handjoy a concise status update, keep ARI and Honcho names understandable, and leave the decision unhurried. |
| `star-clear` | style_probe | Huh. Soft checkpoint. This is only a candidate voice. Not a rollout. The safe path is listen, review, then approve later if it fits. |

The normalized prompts are much more reviewable than raw URLs and task IDs, but
there are still text-normalization and STT clarity issues to fix before a
production Chatterbox path:

- `T T S` was heard as `TS`; this likely needs a spelling form such as
  `text to speech` in operational notifications.
- `cube control` / `kubectl` still came back as `KubeCtrl`; this is
  understandable but should be handled in the normalization layer or avoided in
  spoken user-facing updates.
- `large v three turbo` was heard as `Large B3 Turbo`; use `Whisper large three
  turbo` or avoid speaking exact model names in short notifications.
- `Eyrie` was heard as `ARI` for the Star persona sample despite prompt context;
  continue using the established `airy` pronunciation when that name matters.
- `hand Joy` collapsed to `handjoy`; add punctuation or rephrase when using this
  wording.

## Production candidate architecture

The next production step should be a private sibling service in namespace `ai`,
not a mutation of the stable Kokoro `voice-speech` pod and not a direct
Talon/Star provider switch.

Recommended shape:

1. Build a Nest-managed Chatterbox candidate image from the same ROCm 7.2.4
   PyTorch base used by `voice-speech`.
2. Constrain dependency resolution so Chatterbox cannot replace the ROCm
   `torch`/`torchaudio` stack with CUDA wheels. The temporary acceptance install
   did accidentally pull CUDA wheels into `/tmp/chatterbox_eval`; generation only
   worked after removing those target-local `torch`/`torchaudio` trees so Python
   used the live ROCm stack again.
3. Preserve the `norm_loudness=False` setting, or patch/wrap the reference audio
   path to cast normalized audio back to `float32` before the S3 tokenizer.
4. Mount or bake `files/app/voice-speech/chatterbox-presets/presets.json` and the
   selected reference WAVs into the service image/config.
5. Expose OpenAI-compatible private routes:
   - `GET /health`
   - `GET /v1/audio/voices`
   - `POST /v1/audio/speech`
6. Return named candidate voices `talon-elegant` and `star-clear`; hold aliases
   `talon` and `star` until Joy gives explicit final approval.
7. Keep the stable Kokoro `voice-speech` service running separately until the
   Chatterbox candidate service has warm latency, GTT behavior, STT round-trip,
   and listening-review evidence.

Resource notes:

- Phase 2 saw Chatterbox raise GTT use from about 47.5 GiB before load to about
  50.2 GiB after load and 52.0 GiB after a small grid. This is compatible with
  owl's current headroom, but the sibling service should still request/limit GPU
  and memory separately from `llama-qwen` and `voice-speech`.
- Warm acceptance samples stayed around 0.91-0.95 RTF, slower than Kokoro but
  usable for candidate review. It is not yet a drop-in low-latency notification
  voice.
- Keep STT prompt/context evaluation in every follow-up: listening quality and
  machine transcription are different, and Joy's ear remains authoritative for
  persona fit.

## Rollout boundary

This branch should be reviewed as source and artifact production only. It should
not be merged as a Talon/Star production TTS provider change, and it should not
trigger a live `voice-speech` deployment by itself unless Joy explicitly approves
the next candidate-service implementation.
