# Owl Qwen3.6 MTP rollout notes

These notes describe the MTP experiment that was rolled back after Joy observed
that it reduced the resident `llama-qwen` service from the accepted four-slot,
vision-enabled shape to one text-only slot.  The canonical service now preserves
four-slot Qwen3.6 + `--mmproj` behavior; MTP should be revisited only as an
isolated candidate or after llama.cpp can prove `draft-mtp` with the required
four-slot/vision runtime.

## Superseded source-managed shape

The rolled-back MTP shape kept endpoint `llama-qwen` in namespace `ai`, switched
that endpoint to `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`, and launched it with:

- `--spec-type draft-mtp`
- `--spec-draft-n-max 2`
- `--spec-draft-type-k q4_0`
- `--spec-draft-type-v q4_0`
- `--parallel 1`
- no `--mmproj`

## Compatibility decision

The existing `llama.cpp` build on owl exposes `--spec-type draft-mtp` and
`--spec-draft-n-max`, so the runtime can start the Qwen3.6 MTP path.  The
observed tradeoff is not acceptable for the canonical service: current MTP
behavior did not preserve the previous `--mmproj` vision path or `--parallel 4`
service shape.  Prefer the four-slot resident service unless a future candidate
proves MTP with equivalent concurrency and vision.

## Restore path

Restore the source-managed canonical shape in `data/kubernetes/app/llama-server.yaml`
and `data/kubernetes/service/llama-qwen.yaml`, then redeploy
`nest::eyrie::ai::deploy_llama_qwen`.  The restored resident service should use
the normal Qwen3.6 GGUF artifact, `--parallel 4`, `--mmproj`, and
`--image-max-tokens 4096`.

## Post-rollout verification

After restoring the canonical service, verify:

1. `kubectl -n ai rollout status deploy/llama-qwen`
2. The pod args include `--parallel 4`, `--mmproj`, and `--image-max-tokens` and
   do not include `--spec-type draft-mtp`.
3. `/health` returns OK through the service.
4. `/props` shows `total_slots: 4` and vision enabled.
5. `/slots` exposes four slots, and a short four-request concurrency smoke
   completes without pod restarts.
