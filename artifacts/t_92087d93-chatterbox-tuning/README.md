# t_92087d93 Chatterbox TTS tuning evidence

## Source change summary

The managed `ai/voice-chatterbox` server wrapper was updated from `0.1.0` to `0.1.1` in `data/kubernetes/app/voice-chatterbox.yaml`.

Changes:

- Cache prepared Chatterbox voice conditionals per preset instead of re-reading and re-encoding the reference WAV on every request.
- Expose safe Chatterbox-Turbo generation knobs that are present in the installed `generate()` signature: `temperature`, `top_p`, `top_k`, and `repetition_penalty`.
- Keep `speed` rejected because installed Chatterbox-Turbo has no speed/duration parameter.
- Add default post-processing: leading/trailing trim and mild low-energy inter-phrase attenuation to reduce trailing breath/silence artifacts without a hard gate.
- Extend `/health` and response headers with supported tuning and post-processing evidence.
- Keep the global generation lock. The baseline concurrency probe showed requests serialize today, and this change avoids claiming thread-safety for shared `tts.conds` on ROCm.

## Installed Chatterbox options inspected

`ChatterboxTurboTTS.generate` signature from live package introspection:

```text
(self, text, repetition_penalty=1.2, min_p=0.0, top_p=0.95, audio_prompt_path=None, exaggeration=0.0, cfg_weight=0.0, temperature=0.8, top_k=1000, norm_loudness=True)
```

The source excerpt warns that `cfg_weight`, `min_p`, and `exaggeration` are ignored by Turbo. There is no speed parameter.

## Baseline production evidence

Live service before this source change:

- Pod: `ai/voice-chatterbox-6697b88b86-f58ns`, Ready on `owl`, 0 restarts.
- Health: version `0.1.0`, Chatterbox `0.1.7`, Torch `2.9.1+rocm7.2.4.git39497456`, HIP `7.2.53211-97f5574fe2`, GPU `Radeon 8060S Graphics`.
- Aliases: `talon -> talon-elegant`, `star -> star-clear`.
- `norm_loudness=false`, `production_tts_changed=true`.
- `kubectl top pod` at one idle observation: `2m` CPU, `3232Mi` memory.
- `rocm-smi` was not present in this worker environment, so GPU utilization evidence remains Joy's observed ~60% plus the service timing/concurrency probes here.

## Baseline endpoint benchmark

Endpoint: `http://10.108.157.193/v1/audio/speech`, voice `talon`.

| Sample | Text focus | HTTP | Client wall s | Audio s | Client RTF | WAV |
|---|---|---:|---:|---:|---:|---|
| agent_request_received | Includes “Agent request received” | 200 | 6.089 | 5.600 | 1.087 | `baseline/agent_request_received.wav` |
| ops_tokens | KubeCM / llama-qwen / owl tokens | 200 | 5.516 | 5.480 | 1.007 | `baseline/ops_tokens.wav` |
| short_ack | Short “Done.” notification | 200 | 1.823 | 0.760 | 2.399 | `baseline/short_ack.wav` |
| long_ops | Longer status update | 200 | 13.931 | 12.800 | 1.088 | `baseline/long_ops.wav` |

Concurrency probe with two simultaneous requests:

| Request | Status | Client wall s | Server wall s | Server audio s | Server RTF |
|---:|---:|---:|---:|---:|---:|
| 1 | 200 | 6.623 | 6.613 | 6.440 | 1.027 |
| 2 | 200 | 12.559 | 12.550 | 5.920 | 2.120 |

Total wall for the pair was `12.561s`, confirming effective serialization through the global lock.

## Post-processing candidate artifact comparison

Post-processing was tested offline on the baseline WAVs using the same trim/gate algorithm now staged in source.

| Sample | Before s | After s | Removed s | Trim start s | Trim end s | Gated segments | Before WAV | After WAV |
|---|---:|---:|---:|---:|---:|---:|---|---|
| agent_request_received | 5.600 | 5.390 | 0.210 | 0.000 | 0.210 | 3 | `baseline/agent_request_received.wav` | `postprocess-candidate/agent_request_received.wav` |
| ops_tokens | 5.480 | 5.330 | 0.150 | 0.000 | 0.150 | 4 | `baseline/ops_tokens.wav` | `postprocess-candidate/ops_tokens.wav` |
| short_ack | 0.760 | 0.550 | 0.210 | 0.020 | 0.190 | 0 | `baseline/short_ack.wav` | `postprocess-candidate/short_ack.wav` |
| long_ops | 12.800 | 12.550 | 0.250 | 0.000 | 0.250 | 11 | `baseline/long_ops.wav` | `postprocess-candidate/long_ops.wav` |

## Recommendation

Ship the source change for review, then deploy with KubeCM after approval and run live after-deploy benchmarks against version `0.1.1`. The likely safe latency win is conditionals caching plus reduced returned audio tail; do not remove the global lock until a separate ROCm/thread-safety probe proves shared Chatterbox state is safe under concurrent generation.

Rollback is straightforward: revert the `data/kubernetes/app/voice-chatterbox.yaml` server wrapper and `data/kubernetes/service/voice-chatterbox.yaml` `cutover_revision` bump, then redeploy the prior Chatterbox KubeCM release or switch Hermes TTS back to the Kokoro provider if needed.
