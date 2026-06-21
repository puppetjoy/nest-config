# llama-qwen Strix Halo rocWMMA ROCm benchmark

Date: 2026-06-21
Host: owl / Strix Halo
Image: `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:zen5`
llama.cpp: b9592 / ac4cddeb0
Model: `Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf`
Projector: `Qwen3.6-35B-A3B-mmproj-F16.gguf`

## Build artifact

The zen5 tool image now preserves separate binaries for deliberate comparison:

- `/usr/local/bin/llama-server-vulkan`
- `/usr/local/bin/llama-server-rocm`
- `/usr/local/bin/llama-server-rocm-rocwmma`
- matching `llama-bench-*` binaries for each backend family

The default `/usr/local/bin/llama-server` symlink remains Vulkan. The Kubernetes
`llama-qwen` resident service remains configured for `llama_cpp_backend: vulkan`.

The rebuilt root-owned image was checked before benchmarking:

- final image size: about 8.39 GB
- prior bad image size: about 26.6 GB
- `/usr/local/bin/llama-server-rocm-rocwmma --version`: `9592 (ac4cddeb0)`
- `/usr/lib/debug` and large build trees were absent from the final image

## Benchmark isolation

For the benchmark window, Honcho/self-improvement traffic was quieted:

- Paused Hermes cron jobs:
  - `c15fd7062f45` 6-hour Honcho self-improvement loop
  - `0ca1382c9987` Beryl MR workflow self-improvement loop
  - `0021766a9537` Honcho representation queue maintenance monitor
  - `a55c696c23d6` Honcho representation queue maintenance weekly status
- Scaled Kubernetes deployments to zero:
  - `ai/honcho-deriver`
  - `ai/honcho-embeddings`
  - `ai/llama-qwen-honcho`

After the benchmark, those cron jobs were resumed and the three deployments were
scaled back to one replica and verified available.

## Method

A bounded live `llama-qwen` canary switched `LLAMA_CPP_BACKEND` and the server
arguments per variant, then restored the original resident Vulkan shape in a
`finally` guard.

Common small-shape arguments for the backend comparison:

- `--ctx-size 32768`
- `--parallel 1`
- `--flash-attn on`
- `--no-mmap`
- `--batch-size 2048`
- `--ubatch-size 512`
- `--spec-type draft-mtp --spec-draft-n-max 2`
- `n_predict: 128`, `cache_prompt: false`, `temperature: 0`, `top_k: 1`

The prompt was about 3.9k prompt tokens. Vulkan was also measured in the resident
four-slot long-context shape for a baseline sanity check.

## Results

| Variant | Backend | Shape | Prompt eval avg | Token gen avg | GTT before -> after | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- |
| resident-vulkan-current-shape | Vulkan | ctx 1,048,576 / parallel 4 | 983.71 tok/s | 63.54 tok/s | 72.05 GB -> 72.06 GB | current resident topology |
| vulkan-small-fa-nommap | Vulkan | ctx 32,768 / parallel 1 | 1020.00 tok/s | 67.54 tok/s | 47.33 GB -> 47.49 GB | best result in this run |
| rocm-small-fa-nommap | stock ROCm | ctx 32,768 / parallel 1 | 165.83 tok/s | 30.01 tok/s | 6.13 GB -> 6.13 GB | invalid as GPU benchmark; ROCm did not detect a GPU |
| rocm-rocwmma-small-fa-nommap | ROCm + rocWMMA FATTN | ctx 32,768 / parallel 1 | 161.92 tok/s | 29.79 tok/s | 6.13 GB -> 6.13 GB | invalid as GPU benchmark; ROCm did not detect a GPU |

Joy rejected the first ROCm/rocWMMA timings as valid GPU evidence because the
ROCm server logs did not prove GPU detection/use. The invalid rerun forced
`--n-gpu-layers 999`, used the same small `--flash-attn on --no-mmap` shape, and
briefly added an unconfined/seccomp ROCm test context, but ROCm still did not see
the GPU:

- stock ROCm log: `ggml_cuda_init: failed to initialize ROCm: no ROCm-capable device is detected`
- rocWMMA log: `ggml_cuda_init: failed to initialize ROCm: no ROCm-capable device is detected`
- both logs warned `no usable GPU found, --gpu-layers option will be ignored`
- both pods had `/dev/kfd` and `/dev/dri/renderD128`
- in-container `rocminfo` failed with `HSA_STATUS_ERROR_OUT_OF_RESOURCES`, while
  host `rocminfo` on owl saw the `gfx1151` GPU
- GTT stayed flat at about 5.70 GiB for both ROCm variants, unlike Vulkan's
  tens-of-GiB model residency

That failure was not a missing-device or memlock/capability problem. The live pod
had `HSA_OVERRIDE_GFX_VERSION` present with an empty value from the source Hiera
blank. ROCr treats the empty override as invalid; `env -u HSA_OVERRIDE_GFX_VERSION
rocminfo` immediately enumerated the CPU and Strix Halo GPU from the same pod. The
source-managed fix is commit `806bd2a7`, which unsets the variable before starting
`llama-server` when the Hiera value is blank.

With the blank-override fix deployed, the GPU-detected rerun used
`HSA_OVERRIDE_GFX_VERSION=11.0.0`, `--n-gpu-layers 999`, `--flash-attn on`,
`--no-mmap`, ctx 32,768, and one slot. Both ROCm variants logged `ROCm0 : Radeon
8060S Graphics`, `rocminfo` enumerated HSA agents, GTT/model residency jumped to
~44 GiB, and completions succeeded:

| Variant | Backend | Shape | Prompt eval avg | Token gen avg | GTT before -> after | Conclusion |
| --- | --- | --- | ---: | ---: | ---: | --- |
| rocm-small-fa-nommap-ngl999-hsa1100 | stock ROCm | ctx 32,768 / parallel 1 / `--n-gpu-layers 999` | 767.99 tok/s | 53.57 tok/s | 43.88 GiB -> 44.05 GiB | valid ROCm GPU run |
| rocm-rocwmma-small-fa-nommap-ngl999-hsa1100 | ROCm + rocWMMA FATTN | ctx 32,768 / parallel 1 / `--n-gpu-layers 999` | 665.26 tok/s | 46.55 tok/s | 43.90 GiB -> 44.27 GiB | valid ROCm GPU run; slower here |

For comparison, the same report's Vulkan small-shape row was 1020.00 tok/s prompt
eval and 67.54 tok/s generation, and the resident four-slot Vulkan shape was
983.71 tok/s prompt eval and 63.54 tok/s generation. The rocWMMA FATTN build did
not explain kyuz0's faster Strix Halo prompt-processing numbers in this Nest
image/run; it was slower than stock ROCm and both ROCm variants remained slower
than Vulkan on this bounded server workload.

Raw timing/result files:

- `docs/llama-qwen-strix-halo-rocwmma-benchmark-results.json`
- `docs/llama-qwen-strix-halo-rocwmma-benchmark-rerun-results.json`
- `docs/llama-qwen-strix-halo-rocwmma-gpu-rerun-results.json`

## Recommendation

Do not switch resident `llama-qwen` away from Vulkan. Keep the new stock ROCm and
rocWMMA binaries in the tool image as explicit experimental artifacts, but Vulkan
remains the faster and safer resident backend for this Qwen3.6 UD-Q8_K_XL MTP
server shape. If ROCm is revisited, use a non-empty `HSA_OVERRIDE_GFX_VERSION` for
the ROCm canary or leave the variable truly unset; do not set it to an empty
string.
