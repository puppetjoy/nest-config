# llama-qwen Strix Halo rocWMMA ROCm benchmark

Date: 2026-06-21
Host: owl / Strix Halo
Image: `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:zen5`
llama.cpp: b9592 / ac4cddeb0
Model: `Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf`
Projector: `Qwen3.6-35B-A3B-mmproj-F16.gguf`

## Build artifact

The benchmarked zen5 tool image preserved separate binaries for deliberate
comparison during the experiment:

- `/usr/local/bin/llama-server-vulkan`
- `/usr/local/bin/llama-server-rocm`
- `/usr/local/bin/llama-server-rocm-rocwmma`
- matching `llama-bench-*` binaries for each backend family

The default `/usr/local/bin/llama-server` symlink remains Vulkan. The Kubernetes
`llama-qwen` resident service remains configured for `llama_cpp_backend: vulkan`.
After review, Joy chose to drop the rocWMMA build path and keep only the Vulkan
and stock ROCm backends for future comparison.

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

## Long-context follow-up

Joy asked whether rocWMMA flash-attention fares better at longer context sizes,
where it might plausibly pull ahead of Vulkan. I ran a bounded follow-up with
Honcho/self-improvement traffic quieted again, `--ctx-size 131072`, one slot,
`--flash-attn on`, `--no-mmap`, `--batch-size 2048`, `--ubatch-size 512`, and
64 predicted tokens per row. The ROCm rocWMMA run used
`HSA_OVERRIDE_GFX_VERSION=11.0.0` and `--n-gpu-layers 999`; logs again proved
`ROCm0 : Radeon 8060S Graphics` and `rocminfo` enumerated the HSA agents.

| Variant | Actual prompt tokens | Prompt eval | Token gen | GTT before -> after | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| Vulkan | 8,206 | 902.03 tok/s | 53.12 tok/s | 46.61 GiB -> 46.76 GiB | ctx 131k / parallel 1 |
| Vulkan | 16,367 | 886.49 tok/s | 66.39 tok/s | 46.76 GiB -> 46.76 GiB | ctx 131k / parallel 1 |
| Vulkan | 32,744 | 787.44 tok/s | 52.93 tok/s | 46.76 GiB -> 46.76 GiB | ctx 131k / parallel 1 |
| ROCm + rocWMMA FATTN | 8,206 | 456.01 tok/s | 38.77 tok/s | 46.14 GiB -> 46.51 GiB | ctx 131k / parallel 1 / `--n-gpu-layers 999` |
| ROCm + rocWMMA FATTN | 16,367 | 336.44 tok/s | 29.71 tok/s | 46.51 GiB -> 46.51 GiB | ctx 131k / parallel 1 / `--n-gpu-layers 999` |
| ROCm + rocWMMA FATTN | 32,744 | 216.17 tok/s | 16.32 tok/s | 46.51 GiB -> 46.51 GiB | ctx 131k / parallel 1 / `--n-gpu-layers 999` |

This follow-up did not find the expected long-context win. rocWMMA prompt eval
fell farther behind Vulkan as the prompt grew: about 51% of Vulkan at ~8k tokens,
38% at ~16k, and 27% at ~32k. Token generation also trailed Vulkan in all three
rows. GTT stayed flat after load for both backends, so this run did not reproduce
the earlier stock-ROCm host-memory growth concern, but it also did not provide a
performance reason to move resident `llama-qwen` off Vulkan.

Raw follow-up file:

- `docs/llama-qwen-strix-halo-rocwmma-long-context-results.json`

## Improvement probe

Joy then asked whether something else was wrong, because the ROCm/rocWMMA deficit
is counter to public Strix Halo ROCm/flash-attention narratives. I ran a second
bounded probe in a temporary isolated benchmark pod using the same zen5 image,
PVC, and model, with the resident `llama-qwen` service and Honcho background
consumers scaled down only for the benchmark window and restored afterward.

The probe separates direct `llama-bench` behavior from the prior server canary:

| Variant | Test | Result | Notes |
| --- | ---: | ---: | --- |
| Vulkan | pp8192 | 1027.77 tok/s | direct `llama-bench`, flash-attn on |
| stock ROCm | pp8192 | 776.26 tok/s | `HSA_OVERRIDE_GFX_VERSION=11.0.0`, flash-attn on |
| ROCm + rocWMMA FATTN | pp8192 | 499.55 tok/s | `HSA_OVERRIDE_GFX_VERSION=11.0.0`, flash-attn on |
| ROCm + rocWMMA FATTN | pp8192 | fail | unset HSA sees `gfx1151` but rocBLAS lacks a gfx1151 Tensile library |
| Vulkan | pp16384 | 968.56 tok/s | direct `llama-bench`, flash-attn on |
| stock ROCm | pp16384 | 737.20 tok/s | direct `llama-bench`, flash-attn on |
| ROCm + rocWMMA FATTN | pp16384 | 358.94 tok/s | direct `llama-bench`, flash-attn on |
| stock ROCm | pp32768 | 646.00 tok/s | direct `llama-bench`, flash-attn on |
| ROCm + rocWMMA FATTN | pp512 / tg128 | 754.03 / 39.94 tok/s | direct `llama-bench`, flash-attn on |
| Vulkan | pp512 / tg128 | 1101.60 / 48.29 tok/s | direct `llama-bench`, flash-attn on |

The main improvement is diagnostic rather than deployable: direct `llama-bench`
stock ROCm is substantially better than the server rocWMMA long-context rows, so
part of the frightening result was the server/MTP/long-prompt shape. However,
that did not uncover a ROCm win: direct Vulkan still beat stock ROCm at every
probed prompt length, and stock ROCm beat the rocWMMA flash-attention build.

I also tried tuning the rocWMMA flash-attention microbatch shape:

| Variant | Test | Result | Notes |
| --- | ---: | ---: | --- |
| ROCm + rocWMMA FATTN | pp8192 | 589.81 tok/s | `--ubatch-size 1024` |
| ROCm + rocWMMA FATTN | pp8192 | 629.86 tok/s | `--ubatch-size 2048`, best rocWMMA FATTN row |
| ROCm + rocWMMA FATTN | pp8192 | 586.56 tok/s | `--batch-size 4096 --ubatch-size 1024` |
| ROCm rocWMMA binary, FA off | pp8192 | 752.93 tok/s | disabling flash-attn removes the rocWMMA FATTN path |
| stock ROCm, FA off | pp8192 | 754.21 tok/s | essentially the same as the rocWMMA binary with FA off |

So yes, the rocWMMA result can be improved from about 500 to about 630 tok/s at
pp8192 by increasing `--ubatch-size`, and disabling flash-attention reaches about
753 tok/s. But disabling flash-attention is not a rocWMMA FATTN win, and the best
rocWMMA FATTN row still trails both stock ROCm and Vulkan. The unset-HSA probe
also confirms why the canaries need either a real `HSA_OVERRIDE_GFX_VERSION` such
as `11.0.0` or a future ROCm stack with native `gfx1151` Tensile coverage.

Raw probe files:

- `docs/llama-qwen-strix-halo-rocwmma-improvement-probe-results.json`
- `docs/llama-qwen-strix-halo-rocwmma-tuning-probe-results.json`

## `ROCBLAS_USE_HIPBLASLT=1` follow-up

Joy asked to try `ROCBLAS_USE_HIPBLASLT=1` based on the Strix Halo wiki tuning
note. I reran the direct `llama-bench` probe in an isolated temporary pod with
`HSA_OVERRIDE_GFX_VERSION=11.0.0`, `ROCBLAS_USE_HIPBLASLT=1`, flash-attention on,
and the same UD-Q8_K_XL model/PVC. The probe confirmed GPU use through
`rocminfo` (`gfx1100` / Radeon 8060S) and llama.cpp ROCm device logs.

| Variant | Test | Result | Notes |
| --- | ---: | ---: | --- |
| stock ROCm + hipBLASLt | pp8192 | 794.24 tok/s | slightly above prior stock ROCm 776.26 tok/s |
| stock ROCm + hipBLASLt | pp16384 | 721.86 tok/s | slightly below prior stock ROCm 737.20 tok/s |
| stock ROCm + hipBLASLt | pp32768 | 647.79 tok/s | effectively unchanged from prior stock ROCm 646.00 tok/s |
| ROCm + rocWMMA FATTN + hipBLASLt | pp8192 | 509.34 tok/s | essentially unchanged from prior rocWMMA 499.55 tok/s |
| ROCm + rocWMMA FATTN + hipBLASLt | pp8192 | 617.25 tok/s | `--ubatch-size 2048`, still below prior best 629.86 tok/s |
| ROCm + rocWMMA FATTN + hipBLASLt | pp16384 | 360.61 tok/s | essentially unchanged from prior rocWMMA 358.94 tok/s |
| ROCm + rocWMMA FATTN + hipBLASLt | pp16384 | 403.78 tok/s | `--ubatch-size 2048`, still far below stock ROCm |
| stock ROCm + hipBLASLt | pp512 / tg128 | 859.56 / 41.21 tok/s | token generation still below Vulkan's prior 48.29 tok/s |
| ROCm + rocWMMA FATTN + hipBLASLt | pp512 / tg128 | 796.44 / 41.02 tok/s | still below stock ROCm on prompt eval |

`ROCBLAS_USE_HIPBLASLT=1` did not rescue the rocWMMA flash-attention path. It may
help or hurt individual stock ROCm prompt rows by a few percent, but the longer
rows are effectively unchanged and the rocWMMA FATTN rows remain below stock ROCm
and Vulkan. The pp512/tg128 token-generation row improved versus the previous
stock ROCm row, but still trails the Vulkan row and does not change the resident
backend recommendation.

Raw hipBLASLt probe file:

- `docs/llama-qwen-strix-halo-rocwmma-hipblaslt-results.json`

## Recommendation

Do not switch resident `llama-qwen` away from Vulkan. Keep Vulkan as the resident
backend and keep only the stock ROCm backend alongside it for deliberate future
comparison; drop the rocWMMA build path because every bounded rocWMMA FATTN probe
trailed stock ROCm and Vulkan. If ROCm is revisited, use a non-empty
`HSA_OVERRIDE_GFX_VERSION` for the ROCm canary until the ROCm/Tensile stack has
native `gfx1151` coverage; do not set it to an empty string.
`ROCBLAS_USE_HIPBLASLT=1` can stay on the candidate list as a small stock-ROCm
tuning knob, but it did not make rocWMMA flash-attention competitive in this run.
