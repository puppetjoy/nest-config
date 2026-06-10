# Owl Qwen3.6 MTP rollout notes

Joy chose to prioritize Qwen3.6 MTP/speculative decoding over multimodal and
multi-slot behavior for the resident `llama-qwen` service.

## Current source-managed shape

- Service endpoint remains `llama-qwen` in namespace `ai`; no separate
  `llama-qwen-mtp` instance is managed.
- App template: `data/kubernetes/app/llama-server.yaml`
- Service data: `data/kubernetes/service/llama-qwen.yaml`
- Deploy plan: `plans/eyrie/ai/deploy_llama_qwen.yaml`
- Model repo: `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`
- Resident quant: `Qwen3.6-35B-A3B-UD-Q5_K_M.gguf`
- Runtime flags include:
  - `--spec-type draft-mtp`
  - `--spec-draft-n-max 2`
  - `--spec-draft-type-k q4_0`
  - `--spec-draft-type-v q4_0`
  - `--parallel 1`
  - no `--mmproj`

## Compatibility decision

The existing `llama.cpp` build on owl exposes `--spec-type draft-mtp` and
`--spec-draft-n-max`, so the runtime supports the Qwen3.6 MTP path.  The tradeoff
is intentional: current MTP guidance/behavior does not preserve the previous
`--mmproj` vision path or `--parallel 4` service shape.  Joy explicitly selected
MTP over multimodal capabilities and asked not to deploy a separate benchmark
instance.

## Rollback

Revert the source changes in `data/kubernetes/app/llama-server.yaml` and
`data/kubernetes/service/llama-qwen.yaml`, then redeploy
`nest::eyrie::ai::deploy_llama_qwen`.  The cache PVC is intentionally sized to
retain prior Qwen3.6/Qwen3.5 rollback artifacts while the MTP model is added.

## Post-rollout verification

After deployment, verify:

1. `kubectl -n ai rollout status deploy/llama-qwen`
2. The pod args include `--spec-type draft-mtp`, `--spec-draft-n-max 2`, and do
   not include `--mmproj`.
3. `/health` returns OK through the service.
4. `/props` shows one slot and text-only modalities.
5. A short OpenAI-compatible chat completion returns sane text.
