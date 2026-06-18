# llama-qwen runaway generation guardrails

`ai/llama-qwen` is the local Qwen3.6 service used by Beryl and other private
Hermes/Honcho paths.  A runaway Beryl worker on 2026-06-18 showed why the
service needs both client-side and server-side caps: llama.cpp logged
`reasoning-budget: activated, budget=2147483647 tokens`, task `1262955`
decoded 10537 output tokens, and the slot was released at `n_tokens = 62933`.

## Source-managed caps

The durable guardrails live in source, not as live `kubectl` edits:

- `data/host/owl.yaml` sets Beryl's Hermes `model.max_tokens` to `4096`.
  Hermes reads this from `model.max_tokens` and sends it as the OpenAI-style
  output cap for local-Qwen chat-completion requests when no caller override is
  provided.
- `data/kubernetes/app/llama-server.yaml` wires `--reasoning-budget` into the
  `llama-server` args.
- `data/kubernetes/service/llama-qwen.yaml` sets the active `llama-qwen`
  service override to `reasoning_budget: '2048'`.

These values are intentionally conservative for local worker use: Beryl still
has enough room for useful analysis plus an answer, but omitted request caps no
longer let the model think until a 262K slot fills.

## Expected live shape after approved rollout

After Puppet/KubeCM deployment is approved and applied, the pod args should
include:

```text
--ctx-size 1048576 --parallel 4 --image-max-tokens 4096 --reasoning-budget 2048 --min-p 0.0
```

Beryl's managed Hermes config should include:

```yaml
model:
  provider: custom:llama-qwen
  default: qwen-3.6
  base_url: https://llama-qwen.eyrie/v1
  max_tokens: 4096
```

## Emergency triage

Use read-only checks first:

```bash
kubectl logs -n ai deploy/llama-qwen --since=12h --timestamps \
  | grep -E 'reasoning-budget|n_decoded|released slot|task [0-9]+'

kubectl -n ai get deploy llama-qwen -o jsonpath='{.spec.template.spec.containers[?(@.name=="llama-server")].args}'
```

If logs show another runaway before the source fix is rolled out, prefer a
human-approved rollout of the source-managed caps.  Do not hand-edit the live
Deployment as the final state; any temporary mitigation must be recorded and
followed by source convergence.
