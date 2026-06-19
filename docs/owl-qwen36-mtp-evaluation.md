# Owl Qwen3.6 MTP rollout notes

These notes track the MTP evaluation history for the resident `llama-qwen`
service.  An earlier MTP rollback happened because that candidate dropped the
accepted four-slot, vision-enabled shape to one text-only slot.  The newer
Q8-family benchmark proved the MTP artifacts can run with `--mmproj` and the
same per-slot 262144 context, so the canonical service can use MTP as long as
rollout verification preserves the four-slot/vision topology.  Joy chose the
Strix Halo-oriented UD-Q8_K_XL quant despite the local benchmark's plain-Q8_0
throughput edge because that UD quant is the intended Unsloth/community-aligned
shape for this hardware.

## Current source-managed shape

The resident endpoint remains `llama-qwen` in namespace `ai` and uses the
Unsloth MTP repository:

- `model_repo`: `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`
- `model_file`: `Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf`
- `model_path`: `/cache/models/Qwen3.6-35B-A3B-MTP-UD-Q8_K_XL.gguf`
- `model_url`: `https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf`
- `mmproj_path`: `/cache/models/Qwen3.6-35B-A3B-mmproj-F16.gguf`
- `parallel_requests`: `4`
- `ctx_size`: `1048576` total, which preserves 262144 context per slot for four
  slots
- speculative flags: `--spec-type draft-mtp --spec-draft-n-max 2`

The MTP repository publishes the UD-Q8_K_XL artifact without an MTP prefix, so
the source-managed cache path names it explicitly as `MTP-UD-Q8_K_XL` while
downloading from the repository's `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` file.

## Benchmark evidence

The accepted Q8-family benchmark on owl used `amd_iommu=off`, Vulkan/RADV
STRIX_HALO, one slot, 262144 ctx, `--mmproj`, five repetitions, 128 generated
tokens, `ignore_eos=true`, and `cache_prompt=false`:

| case | tg mean t/s | prompt mean t/s | GTT load delta GiB | MTP acceptance mean |
|---|---:|---:|---:|---:|
| Q8_0 non-MTP + mmproj | 53.91 | 1028.06 | 41.02 | |
| Q8_0 MTP + mmproj + draft n=2 | 72.59 | 1012.70 | 42.91 | 81.3% |
| UD-Q8_K_XL MTP + mmproj + draft n=2 | 68.22 | 958.00 | 44.12 | 88.2% |

UD-Q8_K_XL MTP is the rollout candidate by explicit Joy choice.  The local
benchmark showed plain Q8_0 MTP was faster in absolute token generation and used
less GTT, but UD-Q8_K_XL MTP still preserved mmproj/MTP behavior, had higher MTP
acceptance, and is the intended Strix Halo-oriented Unsloth quant family.

Artifact references:

- `/home/joy/benchmarks/strix-halo-mtp-q8-llama-qwen/comparison.md`
- `/home/joy/benchmarks/strix-halo-mtp-q8-llama-qwen/results/ud_q8_k_xl_mtp_mmproj_spec2.server.log`
- `/home/joy/benchmarks/strix-halo-mtp-q8-llama-qwen/results/ud_q8_k_xl_mtp_mmproj_spec2.props.json`
- `/home/joy/benchmarks/strix-halo-mtp-q8-llama-qwen/results/q8_0_mtp_mmproj_spec2.server.log`
- `/home/joy/benchmarks/strix-halo-mtp-q8-llama-qwen/results/q8_0_mtp_mmproj_spec2.props.json`

## Rollback path

Restore `data/kubernetes/app/llama-server.yaml` and
`data/kubernetes/service/llama-qwen.yaml` to the non-MTP Q8_0 artifact in
`unsloth/Qwen3.6-35B-A3B-GGUF`, remove the `--spec-type draft-mtp` and
`--spec-draft-n-max 2` args, then redeploy `nest::eyrie::ai::deploy_llama_qwen`.
Keep `--parallel 4`, `--mmproj`, and `--image-max-tokens 4096` in either shape.

## Post-rollout verification

After deploying the MTP shape, verify:

1. `kubectl -n ai rollout status deploy/llama-qwen`
2. The pod image/digest and args include the MTP model path, `--parallel 4`,
   `--mmproj`, `--spec-type draft-mtp`, and `--spec-draft-n-max 2`.
3. `/health` returns OK through the service.
4. `/props` shows `total_slots: 4`, per-slot `n_ctx: 262144`, and
   `modalities.vision: true`.
5. Logs include MTP/speculative initialization such as
   `common_speculative_impl_draft_mtp` and `speculative decoding context initialized`.
6. A representative text generation request works.
7. GTT usage stays within expected headroom on owl/Strix Halo.
