#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

os.environ.setdefault("HF_HOME", "/cache/huggingface")
os.environ.setdefault("XDG_CACHE_HOME", "/cache")
os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")
os.environ.setdefault("MIOPEN_FIND_MODE", "2")

import numpy as np
import soundfile as sf
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS

ROOT = Path("/tmp/chatterbox_acceptance")
REFS = ROOT / "references"
OUT = ROOT / "out"

STT_PROMPT = "Talon Star Honcho Eyrie KubeCM llama-qwen GitLab Puppet Kubernetes OpenVox ROCm kubectl owl voice-speech Chatterbox Kokoro"

PRESETS = [
    {
        "persona": "talon",
        "preset": "talon-elegant",
        "source_candidate": "star-alloy-elegant",
        "reference_wav": REFS / "star-alloy-elegant.wav",
        "description": "Talon candidate: warm, focused, clever, clear, calm ops voice; owl-ish without baby/chibi tone.",
        "samples": {
            "notification": "Talon has a review-ready update. The Chatterbox candidate pack is complete, the selected references are source-managed, and production T T S remains unchanged.",
            "ops_update": "Status: cube control in namespace A I reports deploy voice speech ready. The health endpoint is green, the manifest is saved, and Joy can review the audio before any provider switch.",
            "persona": "I am Talon, a small watchful owl at a laptop. I keep the thread focused, name the evidence, and explain the next safe step for Joy without rushing.",
            "style_probe": "[chuckle] Tiny owl checkpoint: the fix is source-managed, the live service is untouched, and the next move waits for approval.",
        },
    },
    {
        "persona": "star",
        "preset": "star-clear",
        "source_candidate": "star-nova-clear",
        "reference_wav": REFS / "star-nova-clear.wav",
        "description": "Star candidate: clear, bright, soft, friendly operations voice for local Chatterbox review.",
        "samples": {
            "notification": "Star has a clear review update. The chosen Chatterbox voice is packaged as a candidate preset, artifacts are ready, and Talon and Star production voices are unchanged.",
            "ops_update": "Status: the local voice speech service is ready on owl. Whisper large v three turbo can transcribe the acceptance samples with the Nest vocabulary prompt.",
            "persona": "I am Star: bright, careful, and easy to follow. I can hand Joy a concise status update, keep Eyrie and Honcho names understandable, and leave the decision unhurried.",
            "style_probe": "[chuckle] Soft checkpoint: this is only a candidate voice, not a rollout. The safe path is listen, review, then approve later if it fits.",
        },
    },
]

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def gtt() -> str:
    try:
        return subprocess.run(["/opt/rocm/bin/rocm-smi", "--showmeminfo", "gtt", "--json"], text=True, capture_output=True, timeout=20, check=False).stdout
    except Exception as exc:
        return f"unavailable: {exc}"

def write_audio(path: Path, wav, sample_rate: int):
    audio = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
    audio = np.squeeze(audio).astype(np.float32, copy=False)
    sf.write(str(path), audio, sample_rate, format="WAV")
    info = sf.info(str(path))
    return float(info.duration), {"codec": info.format, "sample_rate": info.samplerate, "channels": info.channels, "frames": info.frames, "duration": info.duration, "size": path.stat().st_size}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": 1,
        "created_at_utc": "2026-06-10T07:47:21Z",
        "task_id": "t_e9f23762",
        "request_id": "ar-20260610-074245-1df476",
        "provider": "chatterbox-turbo",
        "production_tts_changed": False,
        "norm_loudness": False,
        "stt_prompt": STT_PROMPT,
        "torch": torch.__version__,
        "hip": getattr(torch.version, "hip", None),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "rocm_gtt_before": gtt(),
        "presets": [],
    }
    t0 = time.perf_counter()
    model = ChatterboxTurboTTS.from_pretrained(device=manifest["device"])
    manifest["model_load_seconds"] = round(time.perf_counter() - t0, 3)
    manifest["sample_rate"] = model.sr
    manifest["rocm_gtt_after_load"] = gtt()
    for preset in PRESETS:
        pdir = OUT / preset["preset"]
        pdir.mkdir(parents=True, exist_ok=True)
        entry = {k: v for k, v in preset.items() if k != "samples" and k != "reference_wav"}
        ref_path = preset["reference_wav"]
        entry["reference_wav"] = str(ref_path)
        entry["reference_sha256"] = sha256(ref_path)
        entry["samples"] = []
        for name, text in preset["samples"].items():
            wav_path = pdir / f"{name}.wav"
            started = time.perf_counter()
            wav = model.generate(text, audio_prompt_path=str(ref_path), norm_loudness=False)
            wall = time.perf_counter() - started
            duration, ffprobe = write_audio(wav_path, wav, model.sr)
            entry["samples"].append({
                "name": name,
                "spoken_text": text,
                "wav": str(wav_path),
                "sha256": sha256(wav_path),
                "wall_seconds": round(wall, 3),
                "audio_seconds": round(duration, 3),
                "rtf": round(wall / duration, 3) if duration else None,
                "ffprobe": ffprobe,
            })
        manifest["presets"].append(entry)
    manifest["rocm_gtt_after"] = gtt()
    path = OUT / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(path)

if __name__ == "__main__":
    main()
