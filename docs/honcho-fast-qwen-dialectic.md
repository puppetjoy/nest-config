# Honcho fast Qwen dialectic lane

This branch stages a source-managed `llama-qwen-fast` llama.cpp service for
Honcho's interactive dialectic path.  The existing 122B `llama-qwen` service
remains the medium/high/max dialectic, dreams, summary, deriver, and rollback
lane, but is now intentionally reduced from 3 x 128K slots to 2 x 128K slots to
free shared/GTT memory for the fast-lane canary.

## Model choice

First candidate is `bartowski/Qwen_Qwen3.5-35B-A3B-GGUF`, file
`Qwen_Qwen3.5-35B-A3B-Q4_K_M.gguf`. Initial live co-residency testing
OOM-killed beside the existing 3-slot 122B lane even after reducing to one 32K
slot and a 96Gi cgroup limit. Joy then steered this task to retry 35B-A3B only
after shrinking the existing 122B lane from 3 x 128K slots to 2 x 128K slots,
which should free roughly one 128K slot's worth of shared/GTT memory.

Rationale:

- Joy steered this task toward Qwen3.5-35B-A3B before dense 9B/14B fallbacks,
  and then specifically asked to free 122B headroom before giving up on 35B-A3B.
- The existing 122B service still exposes two 128K slots for higher-quality
  traffic and rollback, while releasing the third slot's memory pressure.
- The fast lane is intentionally conservative at one 32K slot for the first
  post-shrink 35B-A3B co-residency test. If it still fails, downgrade again with
  the recorded OOM and GTT/headroom evidence.
- The service has a separate 48Gi `owl-crypt` cache PVC and fetches the GGUF
  with a curl init container.  That matches the reviewed `honcho-embeddings`
  pattern and avoids relying on llama.cpp direct HTTPS/HF download behavior.

## Source changes

- `data/kubernetes/app/llama-server-fast.yaml` defines the chartless KubeCM app:
  PVC, HF token secret, model-fetch init container, llama-server Deployment, and
  ClusterIP Service.
- `data/kubernetes/service/llama-qwen.yaml` reduces the existing 122B lane to
  `--ctx-size 262144` and `--parallel 2`, preserving two 128K slots.
- `data/kubernetes/service/llama-qwen-fast.yaml` selects the Qwen3.5-35B-A3B
  Q4_K_M model, `--ctx-size 32768`, and `--parallel 1` for a conservative
  one-slot retry after the 122B shrink.
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
- The existing 122B deployment renders `--ctx-size 262144 --parallel 2`.
- The fast deployment uses image
  `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:zen5`, model path
  `/cache/models/Qwen_Qwen3.5-35B-A3B-Q4_K_M.gguf`, one GPU, an 8Gi
  scheduler-fit request with a 96Gi cgroup limit, and one 32K-context slot.
- Honcho minimal/low env vars point to `llama-qwen-fast`; medium/high/max and
  dream env vars still point to `llama-qwen`.

## Live rollout after review

```bash
cd /home/joy/projects/nest/config
git fetch
bolt plan run nest::puppet::deploy
bolt plan run nest::eyrie::ai::deploy_llama_qwen
kubectl -n ai rollout status deploy/llama-qwen --timeout=90m
kubectl -n ai get deploy/llama-qwen -o jsonpath='{.spec.template.spec.containers[0].args}'
# Verify /props total_slots=2 and n_ctx=131072 before deploying the fast lane.

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

Target: minimal under about 8s and low under about 15s if the canary runtime is
fast enough. If 35B-A3B still fails after the 122B shrink, keep the evidence and
fall back to the already-probed 14B or 9B class with source-managed commits.

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
