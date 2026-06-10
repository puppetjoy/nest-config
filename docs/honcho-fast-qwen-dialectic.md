# Honcho fast Qwen dialectic lane

This branch stages a source-managed `llama-qwen-fast` llama.cpp service for
Honcho's interactive dialectic path.  The existing 122B `llama-qwen` service is
left untouched for medium/high/max dialectic, dreams, summary, deriver, and
rollback.

## Model choice

First candidate: `bartowski/Qwen_Qwen3.5-35B-A3B-GGUF`, file
`Qwen_Qwen3.5-35B-A3B-Q4_K_M.gguf`.

Rationale:

- Joy steered this task toward Qwen3.5-35B-A3B before dense 9B/14B fallbacks.
- The model is sparse/MoE with about 3B activated parameters per token, so it
  should be materially faster than the current 122B-A10B lane while preserving
  more quality than a dense 9B fallback.
- The Q4_K_M GGUF is the publisher's recommended default quant and is listed by
  the Hugging Face model API/search as available in the bartowski repo.
- The service has a separate 48Gi `owl-crypt` cache PVC and fetches the GGUF
  with a curl init container.  That matches the reviewed `honcho-embeddings`
  pattern and avoids relying on llama.cpp direct HTTPS/HF download behavior.

## Source changes

- `data/kubernetes/app/llama-server-fast.yaml` defines the chartless KubeCM app:
  PVC, HF token secret, model-fetch init container, llama-server Deployment, and
  ClusterIP Service.
- `data/kubernetes/service/llama-qwen-fast.yaml` selects the 35B-A3B Q4_K_M
  model, `--ctx-size 32768`, and `--parallel 1` for one 32K-context slot.
  Live starts with `--ctx-size 131072 --parallel 4` and then
  `--ctx-size 65536 --parallel 2` both OOM-killed during model/context load
  beside the existing 122B lane, so this keeps the first 35B canary at the
  minimum useful Honcho interactive context before falling back to 14B/9B.
- `plans/eyrie/ai/deploy_llama_qwen_fast.yaml` deploys the new service.
- `plans/eyrie/ai/deploy_llama.yaml` now includes `qwen_fast` alongside the
  original `qwen` switch.
- `data/kubernetes/app/honcho.yaml` routes only
  `DIALECTIC_LEVELS__minimal` and `DIALECTIC_LEVELS__low` to
  `http://llama-qwen-fast/v1`; medium/high/max, dream induction/deduction,
  summary, and deriver stay on `http://llama-qwen/v1`.

## Render checks

```bash
bolt plan run nest::eyrie::ai::deploy_llama_qwen_fast render_to=tmp/render/llama-qwen-fast.yaml
bolt plan run nest::eyrie::ai::deploy_honcho render_to=tmp/render/honcho-fast-dialectic.yaml
```

Expected rendered invariants:

```bash
python3 - <<'PY'
import yaml
for path in ['tmp/render/llama-qwen-fast.yaml', 'tmp/render/honcho-fast-dialectic.yaml']:
    print(path)
    docs = [d for d in yaml.safe_load_all(open(path)) if d]
    print([f"{d.get('kind')}/{d.get('metadata', {}).get('name')}" for d in docs])
PY
```

- `Deployment/llama-qwen-fast`, `Service/llama-qwen-fast`,
  `PersistentVolumeClaim/llama-qwen-fast-cache`, and `Secret/llama-qwen-fast`
  render in namespace `ai`.
- The fast deployment uses image
  `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:zen5`, model path
  `/cache/models/Qwen_Qwen3.5-35B-A3B-Q4_K_M.gguf`, one GPU, a scheduler-fit
  16Gi request with a 96Gi cgroup limit, and one 32K-context slot.
- Honcho minimal/low env vars point to `llama-qwen-fast`; medium/high/max and
  dream env vars still point to `llama-qwen`.

## Live rollout after review

```bash
cd /home/joy/projects/nest/config
git fetch
bolt plan run nest::puppet::deploy
bolt plan run nest::eyrie::ai::deploy_llama_qwen_fast
kubectl -n ai rollout status deploy/llama-qwen-fast --timeout=90m
kubectl -n ai get deploy,pod,svc,pvc -l app=llama-qwen-fast -o wide

kubectl -n ai run qwen-fast-smoke-$(date +%s) --rm -i --restart=Never \
  --image=docker.io/curlimages/curl:8.11.1 --command -- sh -ceu '
    curl -fsS --max-time 10 http://llama-qwen-fast/health
    curl -fsS --max-time 60 -H "content-type: application/json" \
      -d "{\"model\":\"llama-qwen-fast\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: fast lane ok\"}],\"max_tokens\":8,\"temperature\":0}" \
      http://llama-qwen-fast/v1/chat/completions
  '

bolt plan run nest::eyrie::ai::deploy_honcho init=false
kubectl -n ai rollout status deploy/honcho-api --timeout=10m
kubectl -n ai rollout status deploy/honcho-deriver --timeout=10m
```

## Benchmark/sanity probes

Use the Hermes Honcho tools from Talon before and after Honcho rollout, with the
same prompt shape used for previous timing probes:

- `honcho_reasoning(peer='user', reasoning_level='minimal', query='...')`
- `honcho_reasoning(peer='user', reasoning_level='low', query='...')`

Record wall-clock timing, whether answers are coherent and grounded in retrieved
context, and the live Honcho env evidence:

```bash
kubectl -n ai get deploy/honcho-api -o json | jq -r '
  .spec.template.spec.containers[] | select(.name=="api") | .env[] |
  select(.name|test("DIALECTIC_LEVELS__(minimal|low|medium|high|max)|DREAM_")) |
  [.name, .value] | @tsv'
```

Target: minimal under about 8s and low under about 15s if the 35B-A3B runtime is
fast enough.  If it misses those targets or startup fails due to llama.cpp,
Vulkan, memory, or GGUF compatibility, keep the evidence and try a smaller 14B
or 9B fallback in the same `llama-qwen-fast` service shape.

## Rollback

Rollback does not require deleting `llama-qwen-fast`: change Honcho minimal/low
`MODEL` and `BASE_URL` in `data/kubernetes/app/honcho.yaml` back to
`llama-qwen`/`http://llama-qwen/v1`, redeploy Puppet code, and run:

```bash
bolt plan run nest::eyrie::ai::deploy_honcho init=false
kubectl -n ai rollout status deploy/honcho-api --timeout=10m
kubectl -n ai rollout status deploy/honcho-deriver --timeout=10m
```

After rollback, the unused fast lane can remain available for diagnostics or be
scaled/removed through a separate reviewed source change.
