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
| rocm-small-fa-nommap | stock ROCm | ctx 32,768 / parallel 1 | 165.83 tok/s | 30.01 tok/s | 6.13 GB -> 6.13 GB | stable but much slower |
| rocm-rocwmma-small-fa-nommap | ROCm + rocWMMA FATTN | ctx 32,768 / parallel 1 | 161.92 tok/s | 29.79 tok/s | 6.13 GB -> 6.13 GB | stable but no improvement |

Raw timing/result file from the run:

- `docs/llama-qwen-strix-halo-rocwmma-benchmark-results.json`

## Recommendation

Do not switch resident `llama-qwen` away from Vulkan. In this bounded Strix Halo
canary, the rocWMMA-enabled ROCm flash-attention binary was stable, but it was
slightly slower than stock ROCm and roughly six times slower than Vulkan for
prompt processing on the tested 3.9k-token small shape. Token generation was also
less than half the Vulkan rate.

The rocWMMA variant is still useful to keep as an experimental binary in the
tool image for future upstream comparisons, but it does not explain kyuz0-style
prompt-processing gains for this Nest/Portage ROCm 7.2 + llama.cpp b9592 build.
