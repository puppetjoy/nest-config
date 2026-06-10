# Owl voice-speech local TTS bakeoff

## Scope

This is the first local/private TTS quality pass for the Eyrie `ai/voice-speech`
service on `owl`. It keeps production on the existing Kokoro service while adding
source-managed observability and text-normalization improvements that can be
reviewed before rollout.

## Live service survey

Live checks on 2026-06-10 showed:

- Namespace/deployment: `ai/voice-speech`
- Pod: `voice-speech-6874465884-jpd6j`
- Node: `owl`
- Image: `docker.io/rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1`
- Image digest: `docker.io/rocm/pytorch@sha256:7fe531fa185af260352fe7fbb3fa64ad749abe72adf0600a648c4692801b125a`
- Pod resources: requests `cpu=4`, `memory=8Gi`, `squat.ai/gpu=1`; limits
  `cpu=12`, `memory=32Gi`, `squat.ai/gpu=1`
- Health: `torch=2.9.1+rocm7.2.4.git39497456`,
  `cuda_available=true` via ROCm/HIP, device `Radeon 8060S Graphics`,
  `MIOPEN_FIND_MODE=2`
- Metrics snapshot: pod `325Mi` RSS via Metrics Server; Python process RSS
  `254924 KiB`; node `owl` at `31450Mi` / 24% memory; ROCm SMI reported GTT
  total `120259084288` bytes and GTT used `48827691008` bytes at the time of
  the check
- Cached Kokoro voices present on the PVC: `af_heart`, `af_nova`, `af_alloy`
- Cached Whisper STT models present on the PVC: `tiny`, `base`, `small`

The current service is private ClusterIP only and exposes:

- `GET /health`
- `POST /v1/audio/speech` for Kokoro WAV TTS
- `POST /v1/audio/transcriptions` for Whisper STT

## Source changes in this branch

`data/kubernetes/app/voice-speech.yaml` now:

- pins the runtime pip dependencies observed in the proven live pod instead of
  reinstalling floating latest packages on every restart;
- bumps the embedded API version to `0.2.0`;
- adds `GET /v1/audio/voices` for cached/recommended Kokoro voice inventory;
- adds `GET /v1/models` for a simple OpenAI-like model inventory;
- expands `/health` with API version, Kokoro version, loaded STT/TTS models, and
  cached voices;
- supports Kokoro language-code selection by voice prefix instead of always
  initializing the American-English pipeline;
- adds a default-on `normalize` field to `/v1/audio/speech` plus
  `GET /v1/audio/normalize` for inspectable text normalization;
- adds TTS response headers with voice, language, normalization state, audio
  seconds, wall seconds, and real-time factor.

The normalization pass targets operational tokens that performed poorly in the
baseline:

- `kubectl` -> `cube control`
- `KubeCM` -> `cube see em`
- `llama-qwen` -> `llama qwen`
- `Eyrie` -> `airy`
- `OpenVox` -> `open vox`
- `ROCm` -> `rock em`
- Agent Request ids and Kanban task ids -> spelled identifiers
- HTTP(S) URLs -> spoken link host/path instead of raw punctuation

## Kokoro baseline artifacts

Audio artifacts were generated against the live service without changing
production. They are intentionally left untracked for Joy's ear review:

- Baseline manifest:
  `artifacts/voice-speech-baseline-20260610T060825Z/manifest.json`
- Baseline WAVs:
  `artifacts/voice-speech-baseline-20260610T060825Z/*.wav`
- Normalization probe manifest:
  `artifacts/voice-speech-normalized-20260610T061402Z/manifest.json`
- Normalization probe WAVs:
  `artifacts/voice-speech-normalized-20260610T061402Z/*.wav`

The baseline tested five prompts across `af_heart`, `af_nova`, and `af_alloy`:
agent-request notification, technical status, proper nouns, URL/path/id text,
and a natural paragraph. The normalization probe retested the most operationally
sensitive prompts with `af_heart` and `af_nova`.

Representative baseline timings:

| Voice | Prompt | Audio duration | TTS wall | RTF | Whisper tiny transcript issue |
| --- | --- | ---: | ---: | ---: | --- |
| `af_heart` | technical status | 8.88s | 1.41s | 0.159 | `kubectl -n ai` became `Q-Bectal and AI` |
| `af_heart` | proper nouns | 7.28s | 1.34s | 0.184 | `Honcho`, `Eyrie`, `llama-qwen` degraded |
| `af_heart` | URL/path/id | 17.35s | 2.16s | 0.125 | URL and task id were not operationally clear |
| `af_nova` | paragraph | 12.10s | 1.62s | 0.134 | Natural prose was clean |
| `af_alloy` | paragraph | 11.95s | 1.64s | 0.138 | Natural prose was clean |

The first `af_heart` request took 5.86s for 16.57s of audio because it included
voice/model warmup; subsequent Kokoro requests were around 0.11-0.20 RTF.

The normalization probe improved some operational tokens but also showed that
aggressive URL/id spelling can be too verbose and still confuse STT. The source
normalizer therefore keeps known host/path text readable instead of spelling
full URLs character-by-character.

## Kokoro quality findings

- `af_heart` remains the best default candidate from the cached voices: warm,
  clear natural prose and stable timing.
- `af_nova` is a reasonable alternate but tended to merge `Talon ran` into
  `Talonran` in STT, which suggests less clean spacing for status updates.
- `af_alloy` was not obviously better for Joy's operational prompts and had a
  worse `rollout`/proper-noun STT round trip in the baseline.
- Kokoro is fast enough on owl for notifications; the quality gap is mostly
  expressiveness, cadence, and technical-token pronunciation rather than raw
  throughput.
- STT round-trip is useful for regressions but is not the final judge: several
  proper nouns may sound acceptable to a human while Whisper normalizes them to
  common words.

## Stronger TTS candidate survey

This branch does not switch production to a stronger model. The source-managed
next step should be a separate speech image/candidate service so large model
weights and dependency stacks do not contaminate the current stable Kokoro pod.

| Candidate | Fit for owl/ROCm | License / risk | API fit | Recommendation |
| --- | --- | --- | --- | --- |
| Chatterbox-Turbo | Strong first bakeoff target. 350M English model, lower VRAM/compute, paralinguistic tags, and external server projects report ROCm support. | Upstream advertises MIT/open-source; outputs include Resemble Perth watermarking. | Good: existing server wrappers include OpenAI-compatible APIs, or a thin FastAPI wrapper can match `/v1/audio/speech`. | Build a Nest-published ROCm 7.2.4 image and test first. |
| Chatterbox original / multilingual | Higher quality/control and multilingual support, but 500M class and more runtime surface. | Upstream open-source with watermarking. | Good with wrapper work. | Test after Turbo if Turbo quality is promising. |
| F5-TTS | Plausible on owl only with ROCm 7.x; upstream explicitly warns RDNA 3.5/gfx1151 needs ROCm 7.x because ROCm 6.x gives invalid-device-function errors. | Code MIT; pretrained models CC-BY-NC due Emilia data, so commercial/redistribution constraints matter. | Needs wrapper and reference audio/style workflow. | Research/persona-voice candidate, not first production default. |
| CosyVoice2/3 | Quality and streaming features look strong; larger 0.5B LLM-based stack with more complex dependencies. | Check model license per chosen checkpoint; likely more operational complexity. | FastAPI exists upstream, but production wrapper/pinning required. | Second-wave bakeoff after Chatterbox. |
| Dia / Dia2 | Expressive dialogue quality; 1.6B class for Dia, English-only in common release. | Apache-2.0 code/model repo per Nari Labs search result, but size/runtime is heavy. | Existing community servers expose OpenAI-compatible APIs. | Useful for dialogue demos; probably too heavy for short agent notifications. |
| Fish Audio S2/S2 Pro | Strong quality claims and streaming; S2 Pro uses SGLang-style serving. | Hugging Face S2 Pro says Fish Audio Research License; commercial use requires separate license. | Different serving stack; more than a drop-in Kokoro replacement. | Do not productionize without license review and separate service proof. |

## Productionization path

1. Review/merge this Kokoro observability + normalization branch, then deploy the
   existing `voice-speech` service without changing Hermes/Talon/Star defaults.
2. Move the current bootstrap install into a Nest-published image: ROCm 7.2.4
   base, pinned Python dependencies, checked-in server, declared model cache
   paths, and image digest evidence.
3. Add a sibling candidate deployment or parameterized candidate image for
   Chatterbox-Turbo. Keep it private in `ai`, request `squat.ai/gpu: 1`, and use
   the same artifact harness/prompts for A/B testing.
4. Only after Joy reviews audio artifacts should Hermes profile TTS providers be
   pointed at local `voice-speech` for Talon/Star.
