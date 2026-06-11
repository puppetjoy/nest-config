# Kestrel Qwen3.5 llama-server proposal

Kestrel is a host-local Podman target, not an Eyrie/Kubernetes node for this
service. The source of truth is `data/host/kestrel.yaml` plus the reusable
`nest::lib::llama_server` defined resource.

## Live state before review

Read-only probes on 2026-06-11 showed:

- Host: `kestrel`, Linux 6.12.42, `riscv64`.
- GPU: AMD Navi 33 / Radeon RX 7600-class device at `0000:03:00.0`.
- Render node: `/dev/dri/renderD128` exists and is world-readable in the live
  mode captured by the probe.
- `vulkaninfo` is not installed on the host, so Vulkan runtime readiness still
  needs to be proven inside the `nest/tools/llama.cpp` container after review.
- Memory: 124 GiB RAM total, about 48 GiB available during the probe.
- Podman: 5.7.1.
- No live llama Podman container, systemd service, published llama port, or local
  `nest/tools/llama.cpp` image was present at probe time.
- The registry manifest for `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:latest`
  exposes both `linux/amd64` and `linux/riscv64` images.

## Model research

Confirmed Hugging Face tree API sizes for relevant Qwen3.5 dense GGUFs:

| Repo | File | Size |
| --- | --- | ---: |
| `unsloth/Qwen3.5-2B-GGUF` | `Qwen3.5-2B-Q8_0.gguf` | 1.874 GiB |
| `unsloth/Qwen3.5-4B-GGUF` | `Qwen3.5-4B-Q8_0.gguf` | 4.175 GiB |
| `unsloth/Qwen3.5-9B-GGUF` | `Qwen3.5-9B-Q8_0.gguf` | 8.873 GiB |
| `unsloth/Qwen3.5-4B-MTP-GGUF` | `Qwen3.5-4B-Q8_0.gguf` | 4.294 GiB |
| `unsloth/Qwen3.5-9B-MTP-GGUF` | `Qwen3.5-9B-Q8_0.gguf` | 9.114 GiB |

The 9B Q8 candidates are larger than the RX 7600's 8 GiB class VRAM before KV
cache and runtime overhead, so they are not practical for a two-slot GPU-first
configuration. The 4B Q8 candidate is the best practical dense Qwen3.5 model for
this GPU if we keep Joy's 8-bit preference.

The MTP 4B Q8 file is also plausible by size, but the model card currently says
`-np > 1` and `--mmproj` are not supported with MTP. Because Joy's hard shape is
two max-context slots, this proposal keeps the non-MTP 4B Q8 model and leaves MTP
as a one-slot experiment only.

## Proposed initial config

`data/host/kestrel.yaml` now proposes:

```yaml
nest::service::llama_server::instances:
  qwen35:
    repo: unsloth/Qwen3.5-4B-GGUF:Q8_0
    kv_size: 98304
    parallel: 2
    gpu_layers: 999
    flash_attention: true
```

Expected `llama-server` shape:

```sh
llama-server \
  --host 0.0.0.0 \
  --port 8080 \
  --hf-repo unsloth/Qwen3.5-4B-GGUF:Q8_0 \
  --ctx-size 98304 \
  --n-gpu-layers 999 \
  --parallel 2 \
  --flash-attn on
```

Current llama.cpp treats `--ctx-size` as a total context budget split across
`--parallel` slots, so this starts at two slots of 49,152 tokens each.

This is intentionally conservative for first boot: the model file alone is
4.175 GiB, and the Qwen3.5 text config has 32 layers with every fourth layer as
full attention. A rough F16 KV estimate for full-attention layers is about
32 KiB per token, or about 3 GiB at 98,304 total tokens. That leaves limited
headroom on an 8 GiB GPU for Vulkan/runtime overhead. After review, live testing
should try 114,688 and 131,072 total context only if the 98,304 launch is stable.

## Review/deploy verification plan

After Joy accepts the source handoff:

1. Merge/push/deploy the Nest config change.
2. Apply Puppet on `kestrel` once to pull/create/start the container, then inspect
   logs before a second idempotence run.
3. Verify the live command and image:
   - `podman ps -a --format ...`
   - `podman inspect llama-qwen35` create command and image digest.
   - `systemctl status container-llama-qwen35`.
4. Verify API shape:
   - `curl http://kestrel:8080/health`
   - `curl http://kestrel:8080/props`
   - `curl http://kestrel:8080/slots` should show two slots and the expected
     per-slot context.
   - OpenAI-compatible `/v1/chat/completions` smoke.
5. Verify memory/pressure:
   - llama startup logs for Vulkan device selection and buffer allocations.
   - amdgpu/sysfs VRAM/GTT counters if present.
   - host `free -h`, `podman stats`, and container logs after smoke.
6. If stable, increase only one step at a time:
   - 114,688 total context (57,344 per slot)
   - 131,072 total context (65,536 per slot)
   Roll back to 98,304 total context on OOM, Vulkan allocation failure, slot
   instability, or swap pressure.

Rollback is to restore the previous stopped utility instance or set
`ensure: stopped` on `qwen35`, deploy Puppet, apply on Kestrel, and verify port
8080 is no longer listening.
