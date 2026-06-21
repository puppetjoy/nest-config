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

Joy rejected the original ROCm/rocWMMA timings as valid GPU evidence because the
ROCm server logs did not prove GPU detection/use. A follow-up rerun forced
`--n-gpu-layers 999`, used the same small `--flash-attn on --no-mmap` shape, and
briefly added an unconfined/seccomp ROCm test context. ROCm still did not see the
GPU:

- stock ROCm log: `ggml_cuda_init: failed to initialize ROCm: no ROCm-capable device is detected`
- rocWMMA log: `ggml_cuda_init: failed to initialize ROCm: no ROCm-capable device is detected`
- both logs warned `no usable GPU found, --gpu-layers option will be ignored`
- both pods had `/dev/kfd` and `/dev/dri/renderD128`; a privileged/card1 live
  probe also failed the same way
- in-container `rocminfo` failed with `HSA_STATUS_ERROR_OUT_OF_RESOURCES`, while
  host `rocminfo` on owl saw the `gfx1151` GPU
- GTT stayed flat at about 5.70 GiB for both ROCm variants, unlike Vulkan's
  tens-of-GiB model residency

The rerun therefore confirms the ROCm/rocWMMA rows above are CPU-fallback timings,
not meaningful ROCm GPU measurements:

| Variant | Backend | Shape | Prompt eval avg | Token gen avg | GTT before -> after | Conclusion |
| --- | --- | --- | ---: | ---: | ---: | --- |
| rocm-small-fa-nommap-ngl999 | stock ROCm | ctx 32,768 / parallel 1 / `--n-gpu-layers 999` | 165.08 tok/s | 27.31 tok/s | 5.70 GB -> 5.70 GB | invalid CPU fallback |
| rocm-rocwmma-small-fa-nommap-ngl999 | ROCm + rocWMMA FATTN | ctx 32,768 / parallel 1 / `--n-gpu-layers 999` | 168.49 tok/s | 27.44 tok/s | 5.70 GB -> 5.70 GB | invalid CPU fallback |

Raw timing/result files:

- `docs/llama-qwen-strix-halo-rocwmma-benchmark-results.json`
- `docs/llama-qwen-strix-halo-rocwmma-benchmark-rerun-results.json`

## Recommendation

Do not switch resident `llama-qwen` away from Vulkan. The Vulkan rows are still
valid baseline evidence, but this task did not produce a valid ROCm or rocWMMA GPU
benchmark: current Kubernetes/container ROCm runtime initialization fails even
when the binaries, rocWMMA headers/package, `/dev/kfd`, and `/dev/dri/renderD128`
are present.

The source-managed rocWMMA binary is useful to keep as an experimental artifact,
but the next step is to fix ROCm GPU detection inside the Kubernetes/container
runtime before drawing any Strix Halo performance conclusion. Until a ROCm pod
shows `rocminfo`/llama.cpp detecting `gfx1151` and GTT/model residency comparable
to Vulkan, ROCm/rocWMMA timing rows should be treated as CPU-fallback diagnostics
only.
