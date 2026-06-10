# Owl llama-qwen Qwen3.6 evaluation

This note records the evidence behind the source change that promotes the
resident `ai/llama-qwen` service from Qwen3.5-35B-A3B to Qwen3.6-35B-A3B.

## Candidate

Selected candidate: `unsloth/Qwen3.6-35B-A3B-GGUF`,
`Qwen3.6-35B-A3B-UD-Q5_K_M.gguf` with `mmproj-F16.gguf`.

Reasons:

- It is the direct 35B-A3B successor to the current resident
  `bartowski/Qwen_Qwen3.5-35B-A3B-GGUF` model shape.
- Official base model `Qwen/Qwen3.6-35B-A3B` is public, not gated,
  Apache-2.0 licensed, and marked `image-text-to-text`.
- The Unsloth GGUF repo is public, not gated, Apache-2.0 licensed, and
  declares `base_model:Qwen/Qwen3.6-35B-A3B`.
- It preserves the resident service's multimodal requirement by carrying an
  `mmproj-F16.gguf` projector.
- The Q5 quant is close to the current resident Qwen3.5 Q5 file size:
  Qwen3.6 UD-Q5_K_M is 26,456,194,016 bytes; current Qwen3.5 Q5_K_M is
  25,913,186,112 bytes.
- Qwen3.6's native context is 262,144 tokens.  The existing deployment uses
  `--ctx-size 1048576 --parallel 4`, which the current llama.cpp server
  exposes as four 262,144-token slots.

Source URLs:

- Base model: https://huggingface.co/Qwen/Qwen3.6-35B-A3B
- GGUF repo: https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF
- Model file: https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q5_K_M.gguf
- Projector: https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-F16.gguf

Hugging Face API metadata captured 2026-06-10:

- `Qwen/Qwen3.6-35B-A3B`: sha `995ad96eacd98c81ed38be0c5b274b04031597b0`,
  license `apache-2.0`, pipeline `image-text-to-text`, gated `false`.
- `unsloth/Qwen3.6-35B-A3B-GGUF`: sha
  `a483e9e6cbd595906af30beda3187c2663a1118c`, license `apache-2.0`,
  pipeline `image-text-to-text`, gated `false`, GGUF architecture `qwen35moe`,
  context length `262144`.

## Alternatives considered

- `unsloth/Qwen3.6-27B-GGUF`: available and smaller, but it is not the direct
  35B-A3B successor and would change the resident model class from MoE to dense.
- Qwen3.6 MTP GGUFs: promising, but they introduce new runtime flags and newer
  llama.cpp support requirements.  They should be benchmarked as a separate
  optimization after the drop-in successor is stable.
- Hosted `Qwen3.6-Plus`: stronger hosted model, but not a local resident model
  replacement.

## Current live baseline before source switch

Live `ai/llama-qwen` on owl, captured 2026-06-10:

- Image: `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:zen5`
- Image digest: `sha256:ea97c977762881db86e8ca4c052e002279a9be4c9fdb034888d86235d8d1fce9`
- llama.cpp: `b9222-9a532ae4b`
- Model: `/cache/models/Qwen_Qwen3.5-35B-A3B-Q5_K_M.gguf`
- Projector: `/cache/models/mmproj-Qwen_Qwen3.5-35B-A3B-f16.gguf`
- Args: `--ctx-size 1048576 --parallel 4 --mmproj ... --image-max-tokens 4096 --jinja --reasoning off`
- `/props`: `total_slots = 4`, per-slot `n_ctx = 262144`,
  `modalities.vision = true`
- GTT after smoke: 63,551,574,016 / 120,259,084,288 bytes
- VRAM after smoke: 240,672,768 / 536,870,912 bytes
- cgroup memory after smoke: current 22,285,254,656 bytes, peak 33,514,164,224 bytes

Baseline API smoke through a temporary port-forward:

- Single request: 200 completion tokens in 5.04s wall; server timing
  42.39 generated tok/s and 176.96 prompt tok/s.
- Four concurrent requests: 294 total completion tokens in 4.36s wall;
  aggregate wall rate 67.43 completion tok/s.
- Vision smoke: OpenAI-compatible `image_url` request succeeded; response
  identified the green square, red circle, and blue triangle in the synthetic
  image.  OCR text was not emphasized in the answer.

## Runtime support notes

The existing b9222 image is kept for this source change because the live service
already validates qwen35moe, the multimodal projector path, Vulkan, and four
262K slots.  Current search results show Qwen3.6 runs under llama.cpp, while
Ollama/vendor lag can fail when its vendored llama.cpp lacks `qwen35moe` /
`qwen35` architecture support.  Updating the llama.cpp image or adopting MTP is
therefore left as a later benchmarked optimization rather than bundled into the
model swap.

## Rollback

Rollback is a source revert to the previous service values:

- `model_repo: bartowski/Qwen_Qwen3.5-35B-A3B-GGUF`
- `model_file: Qwen_Qwen3.5-35B-A3B-Q5_K_M.gguf`
- `model_path: /cache/models/Qwen_Qwen3.5-35B-A3B-Q5_K_M.gguf`
- `model_url: https://huggingface.co/bartowski/Qwen_Qwen3.5-35B-A3B-GGUF/resolve/main/Qwen_Qwen3.5-35B-A3B-Q5_K_M.gguf`
- `mmproj_file: mmproj-Qwen_Qwen3.5-35B-A3B-f16.gguf`
- `mmproj_path: /cache/models/mmproj-Qwen_Qwen3.5-35B-A3B-f16.gguf`
- `mmproj_url: https://huggingface.co/bartowski/Qwen_Qwen3.5-35B-A3B-GGUF/resolve/main/mmproj-Qwen_Qwen3.5-35B-A3B-f16.gguf`

Do not delete the current Qwen3.5 cache artifacts until Qwen3.6 is accepted and
stable.

## Post-review validation required

After review approval, deploy through the normal KubeCM path and verify:

1. The init container downloads `Qwen3.6-35B-A3B-UD-Q5_K_M.gguf` and
   `Qwen3.6-35B-A3B-mmproj-F16.gguf` into the persistent cache.
2. `/health` is OK.
3. `/props` reports model path, `modalities.vision: true`, 4 slots, and
   per-slot `n_ctx = 262144`.
4. An OpenAI-compatible text chat completion works.
5. An OpenAI-compatible image request identifies image-specific content.
6. Run the same single-request and 4-concurrent request benchmark shapes from
   this note and compare against the Qwen3.5 baseline.
7. Capture GTT/VRAM/cgroup memory and pod restart/log state before acceptance.
