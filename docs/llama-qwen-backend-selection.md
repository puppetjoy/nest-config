# llama-qwen backend selection and comparison

`ai/llama-qwen` uses the Nest `llama.cpp:zen5` tool image.  The zen5 image
builds two explicit server binaries from the same pinned llama.cpp revision:

- `/usr/local/bin/llama-server-vulkan`
- `/usr/local/bin/llama-server-rocm`

`/usr/local/bin/llama-server` remains a symlink to the Vulkan binary so existing
host-local consumers keep the current production behavior.  The Kubernetes
service selects a backend with the KubeCM/Hiera key `llama_cpp_backend`, which
must be either `vulkan` or `rocm`.  `data/kubernetes/service/llama-qwen.yaml`
keeps the resident service on `vulkan` by default; switching it to `rocm` should
be an explicit review-approved rollout.

## Runtime observability

The deployment records the selected backend in pod labels, pod annotations, and
the `LLAMA_CPP_BACKEND` environment variable.  The startup wrapper also logs the
selected backend, the binary path, the image, and the service name before execing
`llama-server`.

Useful checks after a rollout:

```bash
kubectl -n ai get deploy llama-qwen \
  -o jsonpath='{.spec.template.metadata.labels.llama\.cpp/backend}{"\n"}{.spec.template.spec.containers[?(@.name=="llama-server")].env}{"\n"}{.spec.template.spec.containers[?(@.name=="llama-server")].command}{"\n"}'

kubectl -n ai logs deploy/llama-qwen --tail=100 | \
  grep -E 'llama\.cpp backend=|ggml|vulkan|ROCm|HIP|device|Radeon|8060S'

kubectl -n ai run qwen-props-$(date +%s) --rm -i --restart=Never \
  --image=curlimages/curl:8.11.1 \
  --command -- sh -lc 'curl -fsS http://llama-qwen.ai.svc.cluster.local/health; echo; curl -fsS http://llama-qwen.ai.svc.cluster.local/props'
```

For ROCm-specific probes on owl, also watch `/dev/kfd`, `/dev/dri`, GPU busy,
GTT usage, and cgroup memory from the hosting node or pod:

```bash
ssh owl 'for f in /sys/class/drm/card*/device/gpu_busy_percent /sys/class/drm/card*/device/mem_info_gtt_used /sys/class/drm/card*/device/mem_info_gtt_total; do [ -r "$f" ] && printf "%s=" "$f" && cat "$f"; done'
```

## Comparison pattern

Use the same model path, mmproj, context size, parallelism, MTP flags, image
family, and llama.cpp revision for both backends.  For prompt-processing tests,
make cache effects explicit:

- call `/props` and `/health` before each backend run
- send `/completion` or OpenAI-compatible requests with `cache_prompt:false`
- include a unique nonce in each prompt so prompt-cache reuse cannot hide work
- record `timings.prompt_n`, `timings.prompt_ms`, `timings.prompt_per_second`,
  `timings.predicted_n`, `timings.predicted_ms`, and
  `timings.predicted_per_second`
- record pod args, backend label/env, startup log backend line, GPU busy/GTT, and
  cgroup memory before and after the request

Do not report a ROCm/Vulkan winner unless both backends were actually started
from the source-managed image and measured under the same request shape.  Prior
throwaway measurements suggested ROCm may be slower for medium and large prompt
eval on owl despite high GPU busy; treat that as a hypothesis to re-test with the
source-managed dual-backend image, not as settled evidence for this change.

## Rollout boundary

A merge can safely preserve Vulkan production behavior because the service
override remains `llama_cpp_backend: vulkan`.  A live ROCm switchover is a
separate side effect: change the service override to `rocm`, deploy
`nest::eyrie::ai::deploy_llama_qwen`, and verify the pod starts the ROCm binary
and reports healthy `/props` before sending traffic that matters.
