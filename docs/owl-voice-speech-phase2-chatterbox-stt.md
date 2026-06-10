# Owl voice-speech Phase 2: Chatterbox-Turbo and STT track

## Scope

This Phase 2 pass compares Resemble AI Chatterbox-Turbo against the deployed
Kokoro `af_heart` baseline on the same operational prompts from Phase 1 and keeps
the local STT replacement track active. It does not switch Talon, Star, Hermes,
or the stable `ai/voice-speech` production TTS/STT providers.

## Chatterbox-Turbo source/deployability survey

Sources checked on 2026-06-10:

- `https://github.com/resemble-ai/chatterbox` at
  `3f35dfc8fbe63e5b29793289dc68f1875bb317a5`
- `https://huggingface.co/ResembleAI/chatterbox-turbo`
- `https://github.com/devnen/Chatterbox-TTS-Server` at
  `915ae289340e10c6047f27f47e22eae9bf350c32`

Findings:

- Upstream Chatterbox is MIT licensed and advertises Chatterbox-Turbo as a
  350M-parameter English model for low-latency voice agents, with native
  paralinguistic tags such as `[laugh]`, `[cough]`, and `[chuckle]`.
- The Hugging Face model card documents `ChatterboxTurboTTS.from_pretrained` and
  `model.generate(..., audio_prompt_path=...)`; Turbo requires a reference audio
  clip for voice conditioning.
- The upstream `pyproject.toml` currently pins `torch==2.6.0` and
  `torchaudio==2.6.0` for Python < 3.14. That is not directly deployable on the
  owl ROCm 7.2.4 service image, which already carries
  `torch 2.9.1+rocm7.2.4`.
- The devnen OpenAI-compatible server has explicit ROCm and Strix Halo Docker
  surfaces, including `requirements-strixhalo.txt` and
  `docker-compose-strixhalo.yml`, with ROCm 7.2 / Strix Halo environment knobs
  such as `HSA_XNACK=1`, `PYTORCH_ALLOC_CONF=expandable_segments:True`, and
  `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`.
- A source-managed production candidate should therefore be a sibling private
  service/image, not a mutation of the current Kokoro pod: build from the ROCm
  7.2.4 PyTorch base, keep the existing torch/torchaudio stack, install
  Chatterbox with dependency constraints that avoid downgrading/replacing ROCm
  torch, and expose an OpenAI-compatible `/v1/audio/speech` boundary.

## Temporary evaluation method

To avoid changing production providers or globally contaminating the stable
service, the bakeoff used a temporary pod-local Python target install inside the
existing `ai/voice-speech` pod. The install wrote under `/tmp` only, used the
existing ROCm torch from `/opt/venv`, and was not added to the service startup
path. The first attempt exposed two integration issues that must be accounted for
in any source-managed candidate image:

- A normal venv install tried to pull CUDA torch/torchaudio and lost ROCm device
  access. The candidate image must constrain dependency resolution around the
  ROCm base torch.
- Turbo's default `norm_loudness=True` path promoted the reference audio to
  float64 through pyloudnorm, then the S3 tokenizer failed on ROCm with
  `expected scalar type Float but found Double`. The generated artifacts used
  `norm_loudness=False`; a production wrapper should cast reference audio back to
  float32 or patch/wrap that path deliberately.

Chatterbox-Turbo was conditioned on the Kokoro `af_heart` natural paragraph WAV
only as a neutral >=5s reference for zero-shot generation. This is not a final
Talon/Star persona voice choice.

## Artifacts

Artifacts are intentionally left untracked for Joy's ear review:

- Prompt set:
  `artifacts/phase2-voice-20260610T063253Z/prompts.json`
- Kokoro baseline manifest/audio:
  `artifacts/phase2-voice-20260610T063253Z/kokoro-af_heart/manifest.json`
  and `*.wav`
- Chatterbox-Turbo manifest/audio:
  `artifacts/phase2-voice-20260610T063253Z/chatterbox-turbo/manifest.json`
  and `*.wav`
- STT evaluation manifest:
  `artifacts/phase2-voice-20260610T063253Z/stt/manifest.json`

## TTS timing comparison

| Prompt | Kokoro audio | Kokoro wall | Kokoro RTF | Chatterbox audio | Chatterbox wall | Chatterbox RTF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| agent request notification | 17.50s | 2.26s | 0.129 | 14.80s | 16.25s | 1.098 |
| technical status | 13.68s | 1.90s | 0.139 | 13.24s | 12.04s | 0.909 |
| proper nouns | 9.43s | 1.53s | 0.163 | 11.08s | 10.41s | 0.940 |
| URL/path/task IDs | 18.20s | 2.22s | 0.122 | 18.44s | 19.04s | 1.032 |
| natural paragraph | 13.15s | 1.89s | 0.144 | 11.96s | 14.31s | 1.197 |

The observed averages were approximately 0.14 RTF for warm Kokoro and 1.04 RTF
for Chatterbox-Turbo. Chatterbox-Turbo is usable for offline artifact generation
but was far slower than the current Kokoro service in this temporary integration.
Model load was 4.4s after the weights were cached; the first uncached download
was about 33s for ten Hugging Face files.

ROCm SMI GTT used-memory snapshots during the Chatterbox run:

- before Turbo load: 47.5 GiB
- after Turbo load: 50.2 GiB
- after all five samples: 52.0 GiB

## TTS quality notes

Human review remains authoritative, but operational observations from generated
artifacts and STT round trips are:

- Kokoro `af_heart` remains much faster and consistently understandable for
  notifications.
- Chatterbox-Turbo sounds viable enough to keep as the next candidate path, but
  the temporary Kokoro-reference setup did not make it an obvious drop-in win for
  short operational updates. It also stretched some technical text and made STT
  hear `kubectl`/URL fragments worse than Kokoro.
- Chatterbox-Turbo's expressiveness controls and paralinguistic tags are still
  worth a source-managed candidate service/image pass, especially once a better
  reference/persona clip is selected.
- Do not switch Talon/Star/Hermes production TTS to local Chatterbox from these
  results alone.

## STT track results

The STT probe transcribed Kokoro and Chatterbox `proper_nouns` and
`technical_status` WAVs with Whisper `base`, `small`, `medium`, and
`large-v3-turbo`. Each run used fixed English, `temperature=0.0`,
`condition_on_previous_text=false`, and then repeated with this prompt:

`Talon Star Honcho Eyrie KubeCM llama-qwen GitLab Puppet Kubernetes OpenVox ROCm kubectl owl Eyrie`

Key findings:

- Prompting was a clear win for proper nouns. For example, `small` changed the
  Kokoro proper-noun transcript from `Hancho, Aerie, CubeCM, LamaQN, ... RockM`
  to `Honcho Eyrie KubeCm llama-qwen ... ROCm`; `base` and `medium` showed the
  same pattern.
- `large-v3-turbo` is fast and feasible on owl in this service context: load was
  18.6s, and prompted proper-noun RTF was about 0.040 for Kokoro and 0.034 for
  Chatterbox in the direct probe.
- Bigger Whisper alone does not fully solve local names. `large-v3-turbo` still
  heard Chatterbox `Honcho` as `Oncho`, and unprompted Kokoro `Eyrie` as `Arie`.
- Technical-command speech remains the harder case. Even prompted,
  Chatterbox-Turbo technical status was transcribed as variants of `QPUTELS` /
  `HTT TTOTS`, while Kokoro with normalization kept the command more
  understandable (`cube control` / `kubectl` variants) but still struggled with
  URLs.

The source change in this branch extends the service API so the real endpoint can
be used for this STT path rather than only an ad-hoc direct script:

- `/v1/models` now advertises `whisper-medium`, `whisper-large-v3-turbo`, and
  `whisper-large-v3` in addition to the existing cached models.
- `/health` reports cached Whisper model files.
- `/v1/audio/transcriptions` now accepts `temperature`,
  `condition_on_previous_text`, and `initial_prompt` form fields, while
  continuing to default to deterministic English-friendly settings.

## Recommendation

1. Keep deployed Kokoro `af_heart` as the local baseline and keep Talon/Star on
   the current production TTS provider until Joy reviews the Phase 2 audio.
2. If Joy likes the Chatterbox-Turbo artifacts, build a real sibling private
   `ai` candidate service/image next. The first productionization task is not
   voice quality; it is dependency hygiene around ROCm torch plus a float32
   reference-audio fix.
3. Continue the STT path with Whisper `large-v3-turbo` plus prompt/context
   support as the next practical candidate. The endpoint changes here make that
   testable through `/v1/audio/transcriptions` without a production switch.
4. Research F5-TTS next if Joy wants persona/reference-voice quality more than
   notification latency; research CosyVoice2 if streaming quality becomes the
   priority. Do not fan out into many large installs before reviewing these
   Chatterbox artifacts.
