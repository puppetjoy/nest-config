# Owl speech GPU verification

`ai/voice-speech` requires Owl's ROCm GPU. CPU fallback is not an acceptable
steady state. The selected Kokoro 82M voices, Whisper models, image, and PVC
remain unchanged.

## Diagnosis

The old running container reported no CUDA/HIP device despite requesting
`squat.ai/gpu`. Inspection found no `/dev/kfd` or render node, no GPU devices
in its OCI spec, and no speech entry in the kubelet device allocation checkpoint.
The current plugin configuration includes both device nodes; the recreated
Qwen container has a checkpoint allocation and both nodes. UID/root permissions,
visibility environment variables, and missing compiled `gfx1151` support were
not the cause of this particular failure. The installed PyTorch build explicitly
includes `gfx1151`, matching Owl's KFD topology.

The historical kubelet journal for the original container start was unavailable.
The missing allocation is established; its historical admission/recovery trigger
is not. Do not infer a specific kubelet race or modify the working plugin on
that evidence alone. Recreate the speech deployment through KubeCM to request a
fresh allocation, then verify the checkpoint, container nodes and actual inference.
Do not work around missing allocation with privileged mode or host device mounts.

Kokoro 0.9.4 auto-selects CUDA when available. Its old CPU placement followed the
missing devices, rather than an independently hard-coded CPU setting. The server
now passes `device='cuda'` explicitly and checks both TTS and STT parameters and
actual encoder/decoder tensor devices on every inference request.

## Managed deployment and checks

From the isolated Nest project worktree:

```sh
bolt module install
bolt inventory show owl --detail --format json
bolt command run 'id -un && hostname -f' --targets owl --stream
bolt plan run nest::eyrie::ai::deploy_voice_speech render_to=/modules/nest/voice-speech-rendered.yaml
bolt plan run nest::eyrie::ai::deploy_voice_speech
kubectl -n ai rollout status deployment/voice-speech --timeout=300s
python3 scripts/voice-speech-gpu-check.py --output "$TMPDIR/voice-speech-after.json"
```

The diagnostic runs on Owl so `/proc/meminfo` and DRM telemetry describe the
serving host. It uses a harmless fixed sentence, checks valid non-silent WAV
output and expected transcription words, and records latency, host MemAvailable,
GPU busy/GTT/VRAM samples, container memory/RSS and open GPU descriptors. It does
not send audio to Joy or another messaging service. `--baseline` permits recording
the old CPU behavior for comparison; it does **not** certify GPU success.

Run the bounded check again after warm-up to separate model-loading/kernel-cache
latency from resident inference. Compare both cold and warm memory, not only RSS:
Owl shares RAM between CPU and GPU, and moving weights to GTT need not reduce
host memory pressure. Preserve Qwen's model/context/quantization and use the
existing Recreate strategy so old and new speech models do not overlap.

Focused policy regressions (no local model loading):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  spec/app/test_voice_speech_gpu.py \
  spec/app/hermes/test_voice_speech_tts_command.py -v
```

## Health semantics and intentional CPU work

- `/live` means the HTTP process is alive, not that inference is healthy.
- `/health` returns HTTP 503 for unavailable required GPU, loaded CPU parameters,
  or a retained model-load/inference failure. Inspect `errors`; do not conceal a
  failed operation by selecting CPU. Correct the cause and restart through the
  managed deployment, or explicitly retry against the pod after diagnosis.
- `effective_devices` reports loaded model parameter devices by language/model.
  Empty maps mean not loaded, not proven GPU inference.
- `inference` records the latest successful request's GPU parameter devices and
  actual encoder/decoder input/output devices and call counts. Availability or
  empty evidence alone is not proof that a model executed.
- Text normalization/phonemization, audio decoding/resampling/WAV encoding,
  packed-sequence length metadata, Whisper token sampling/text decoding and
  Kokoro's final audio copy intentionally use the CPU. Neural encoder/decoder
  inference must use the GPU. No unsupported kernel may silently fall back.
- The existing hourly roundtrip monitor now requires successful GPU placement
  evidence for both speech paths, not just a plausible transcript and audio file.
