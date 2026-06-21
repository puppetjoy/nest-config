# llama-qwen Strix Halo PP tuning benchmark

This note records a bounded live canary on owl for the resident `ai/llama-qwen`
service after comparing Joy's measurements with kyuz0's Strix Halo benchmark
grid.  The goal was to check whether our service was missing an obvious
prompt-processing tuning such as flash attention, `--no-mmap`, smaller context
windows, or explicit batch/ubatch settings.

## Scope and restore state

The canary temporarily patched the live Kubernetes Deployment and restored the
original Deployment template afterward.  The service was verified healthy after
restore with:

- backend label/env: `rocm`
- args: `--ctx-size 1048576 --parallel 4 --mmproj ... --image-max-tokens 4096 --reasoning-budget 2048 --min-p 0.0 --spec-type draft-mtp --spec-draft-n-max 2`
- `/props`: build `b9592-ac4cddeb0`, model
  `Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf`, `total_slots: 4`, per-slot
  `n_ctx: 262144`, vision/video modalities present

No source-managed production tuning was promoted by this benchmark.

## Method

Requests went through `/completion` against a local `kubectl port-forward` to the
service.  Each run used:

- `stream: false`
- `cache_prompt: false`
- `temperature: 0`, `top_k: 1`
- `ignore_eos: true`
- fresh nonce per prompt
- 128 predicted tokens

This is still not a perfect `llama-bench` reproduction: it includes
`llama-server`, HTTP, slot, prompt formatting, MTP, and multimodal server shape.
However, it is useful for checking whether a service-level flag change obviously
closes the gap.

## Results

| Variant | Backend | Service shape | Prompt tokens | PP tok/s avg | PP tok/s warm reps | TG tok/s avg | Notes |
|---|---:|---|---:|---:|---:|---:|---|
| current service | ROCm | ctx 1048576, parallel 4; no explicit `--flash-attn`/`--no-mmap` | 576 | 599.7 | 603.2 | 55.4 | Restored production shape |
| small ctx baseline | ROCm | ctx 32768, parallel 1, explicit `--batch-size 2048 --ubatch-size 512` | 512 | 664.4 | 706.9 | 62.9 | Closest PP512-style run |
| small ctx tuned | ROCm | ctx 32768, parallel 1, explicit batch/ubatch, `--flash-attn on --no-mmap` | 560 | 615.9 | 635.5 | 64.2 | No clear PP gain from the kyuz0 flags in this service path |
| small ctx tuned | Vulkan/RADV | ctx 32768, parallel 1, explicit batch/ubatch, `--flash-attn on --no-mmap` | 560 | 713.7 | 792.8 | 59.4 | Best measured PP here, still below kyuz0's grid |

A larger current-shape prompt was also sampled at 833 prompt tokens on ROCm and
averaged 664.9 PP tok/s / 56.2 TG tok/s.

## Interpretation

The obvious kyuz0 command-line hints did not close the gap for our live service
shape:

- Shrinking the server from four 262K slots to one 32K slot improved ROCm PP from
  about 600 tok/s to about 664 tok/s average, or about 707 tok/s after the first
  request.  That is useful overhead evidence, but still far from kyuz0's roughly
  1093 tok/s ROCm PP512 figure.
- Adding `--flash-attn on --no-mmap` on top of the 32K/one-slot ROCm shape did
  not improve prompt processing in this canary; it was slightly lower on PP and
  only slightly higher on token generation.
- Vulkan/RADV with the tuned 32K/one-slot shape was faster than ROCm in this
  service canary for prompt processing, with warm repetitions around 793 tok/s,
  but it still did not match kyuz0's roughly 1045 tok/s Vulkan/RADV PP512 figure.

The remaining gap is likely not a single missing flag.  The comparison is not
apples-to-apples because kyuz0's grid is `llama-bench` PP512/TG128, while this
service path includes `llama-server`, HTTP, slot management, Qwen3.6 MTP,
`mmproj`, Kubernetes/container overhead, and live system noise.  The active Nest
image is also a Gentoo-built b9592/ac4cddeb0 stack with ROCm 7.2.0 and Mesa
26.0.4, while kyuz0's cited grid uses selected toolbox/backend variants such as
ROCm 7.2.3/7.2.4 and tuned RADV/AMDVLK combinations.

## Current stack boundaries

The source-managed Nest image currently builds two `llama-server` binaries from
the same llama.cpp revision:

- Vulkan: `GGML_VULKAN=ON`, using Gentoo Mesa/vulkan-loader; no AMDVLK package is
  source-managed for this image.
- ROCm: `GGML_HIP=ON`, `AMDGPU_TARGETS=['gfx1100', 'gfx1151']`, with Gentoo
  ROCm packages (`rocm-core`, `rocBLAS`, `hipBLAS`) observed at 7.2.0 in the
  running image.

`rocWMMA`/improved and AMDVLK variants are therefore outside the current
Nest-managed stack.  Testing them should be a separate source-managed package and
image-build task rather than an ad-hoc live flag change.

## Recommendation

Do not promote `--flash-attn on --no-mmap` or a one-slot 32K resident shape as a
permanent production fix from this evidence.  For Joy's real Hermes/Honcho
workloads, keep the restored ROCm service shape unless a separate review approves
a rollback to Vulkan or a deliberate context/parallel tradeoff.

If we want an apples-to-apples kyuz0 comparison, the next step should be a
source-managed `llama-bench` target in the Nest `llama.cpp:zen5` build and a
quiet benchmark pod/run that temporarily owns the GPU/PVC, reports raw
`llama-bench -pg 512,128 -c 32768/65536 -fa 1 --no-mmap` output for both
Vulkan and ROCm, then restores the resident service.  AMDVLK or rocWMMA/improved
should be separate package-stack experiments.
