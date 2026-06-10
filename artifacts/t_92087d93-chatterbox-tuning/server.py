import hashlib
import importlib.metadata
import io
import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from chatterbox.tts_turbo import ChatterboxTurboTTS

app = FastAPI(title='Nest voice-chatterbox', version='0.1.1')
device = 'cuda' if torch.cuda.is_available() else 'cpu'
lock = threading.Lock()
model = None
model_loaded_at = None
conditionals_cache = {}

TRIM_RELATIVE_DB = 42.0
GATE_RELATIVE_DB = 46.0
GATE_ATTENUATION = 0.18

PRESET_ROOT = Path('/presets')
PRESETS_PATH = PRESET_ROOT / 'presets.json'
with PRESETS_PATH.open() as fh:
    preset_manifest = json.load(fh)

presets = {preset['preset']: preset for preset in preset_manifest['presets']}
active_aliases = {
    preset['alias_after_final_approval']: preset['preset']
    for preset in preset_manifest['presets']
    if preset.get('alias_after_final_approval')
}
pending_aliases = {}

PRONUNCIATIONS = [
    ('KubeCM', 'cube see em'),
    ('kubectl', 'cube control'),
    ('Eyrie', 'airy'),
    ('OpenVox', 'open vox'),
    ('ROCm', 'rock em'),
]

class SpeechRequest(BaseModel):
    input: str
    model: str = 'chatterbox-turbo'
    voice: str = 'talon-elegant'
    response_format: str = 'wav'
    speed: float = 1.0
    normalize: bool = True
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int = 1000
    repetition_penalty: float = 1.2
    postprocess_audio: bool = True


def dependency_version(name):
    try:
        return importlib.metadata.version(name)
    except Exception:
        return None


def normalize_for_tts(text: str):
    normalized = text
    for source, replacement in PRONUNCIATIONS:
        normalized = normalized.replace(source, replacement)
    return ' '.join(normalized.split()).strip()


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_voice(voice: str):
    preset_name = active_aliases.get(voice, voice)
    if preset_name not in presets:
        if voice in pending_aliases:
            raise HTTPException(status_code=409, detail=f'Voice alias {voice!r} is pending final approval; use {pending_aliases[voice]!r}')
        raise HTTPException(status_code=400, detail=f'Unsupported Chatterbox voice: {voice}')
    return preset_name, presets[preset_name]


def get_model():
    global model, model_loaded_at
    if model is None:
        started = time.perf_counter()
        model = ChatterboxTurboTTS.from_pretrained(device=device)
        model_loaded_at = time.perf_counter() - started
    return model


def validate_generation_options(request: SpeechRequest):
    if request.speed != 1.0:
        raise HTTPException(status_code=400, detail='Chatterbox-Turbo does not expose duration/speed control; use generation quality knobs instead')
    if not 0.05 <= request.temperature <= 2.0:
        raise HTTPException(status_code=400, detail='temperature must be between 0.05 and 2.0')
    if not 0.05 <= request.top_p <= 1.0:
        raise HTTPException(status_code=400, detail='top_p must be between 0.05 and 1.0')
    if not 1 <= request.top_k <= 2000:
        raise HTTPException(status_code=400, detail='top_k must be between 1 and 2000')
    if not 1.0 <= request.repetition_penalty <= 2.0:
        raise HTTPException(status_code=400, detail='repetition_penalty must be between 1.0 and 2.0')


def get_conditionals(tts, preset_name: str, reference: Path):
    cached = conditionals_cache.get(preset_name)
    if cached is None:
        tts.prepare_conditionals(str(reference), exaggeration=0.0, norm_loudness=False)
        cached = tts.conds
        conditionals_cache[preset_name] = cached
    return cached


def frame_rms(data, frame: int, hop: int):
    if len(data) < frame:
        padded = np.pad(data, (0, frame - len(data)))
    else:
        extra = (-(len(data) - frame)) % hop
        padded = np.pad(data, (0, extra))
    return np.array([
        np.sqrt(np.mean(padded[start:start + frame] ** 2) + 1e-12)
        for start in range(0, len(padded) - frame + 1, hop)
    ])


def postprocess_audio(data, sample_rate: int):
    metrics = {
        'enabled': True,
        'trim_start_seconds': 0.0,
        'trim_end_seconds': 0.0,
        'gated_segments': 0,
    }
    if data.size == 0:
        return data, metrics
    peak = float(np.max(np.abs(data))) or 1.0
    frame = max(int(sample_rate * 0.02), 1)
    hop = max(int(sample_rate * 0.01), 1)
    rms = frame_rms(data, frame, hop)
    floor = float(np.percentile(rms, 10)) if rms.size else 0.0
    trim_threshold = max(peak * 10 ** (-TRIM_RELATIVE_DB / 20), floor * 4.0, 1e-4)
    active = np.flatnonzero(rms > trim_threshold)
    processed = data
    offset = 0
    if active.size:
        pad = int(sample_rate * 0.08)
        start = max(int(active[0] * hop) - pad, 0)
        end = min(int(active[-1] * hop) + frame + pad, len(data))
        metrics['trim_start_seconds'] = round(start / sample_rate, 3)
        metrics['trim_end_seconds'] = round((len(data) - end) / sample_rate, 3)
        processed = data[start:end]
        offset = start
    if processed.size == 0:
        return processed, metrics
    rms = frame_rms(processed, frame, hop)
    floor = float(np.percentile(rms, 10)) if rms.size else 0.0
    gate_threshold = max(peak * 10 ** (-GATE_RELATIVE_DB / 20), floor * 6.0, 2e-4)
    quiet = rms < gate_threshold
    gated = processed.copy()
    i = 0
    edge_pad_frames = max(int(0.18 * sample_rate / hop), 1)
    min_frames = max(int(0.06 * sample_rate / hop), 1)
    while i < len(quiet):
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < len(quiet) and quiet[j]:
            j += 1
        if j - i >= min_frames and i > edge_pad_frames and j < len(quiet) - edge_pad_frames:
            start = max(i * hop, 0)
            end = min(j * hop + frame, len(gated))
            gated[start:end] *= GATE_ATTENUATION
            metrics['gated_segments'] += 1
        i = j
    metrics['trim_offset_seconds'] = round(offset / sample_rate, 3)
    return gated, metrics


def audio_to_float32(audio):
    data = audio.detach().cpu().numpy() if hasattr(audio, 'detach') else np.asarray(audio)
    return np.squeeze(data).astype(np.float32, copy=False)


def write_wav(data, sample_rate: int):
    out = io.BytesIO()
    sf.write(out, data, sample_rate, format='WAV')
    return out.getvalue(), len(data) / sample_rate


@app.get('/health')
def health():
    reference_state = {}
    for name, preset in presets.items():
        path = PRESET_ROOT / name / 'reference.wav'
        reference_state[name] = {
            'exists': path.exists(),
            'sha256_ok': path.exists() and sha256(path) == preset.get('reference_sha256'),
        }
    return {
        'ok': True,
        'version': app.version,
        'model_loaded': model is not None,
        'model_load_seconds': round(model_loaded_at, 3) if model_loaded_at else None,
        'torch': torch.__version__,
        'hip': getattr(torch.version, 'hip', None),
        'cuda_available': torch.cuda.is_available(),
        'device': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        'chatterbox_tts': dependency_version('chatterbox-tts'),
        'aliases_active': active_aliases,
        'aliases_pending_final_approval': pending_aliases,
        'voices': sorted(presets.keys()),
        'reference_state': reference_state,
        'norm_loudness': False,
        'conditionals_cached': sorted(conditionals_cache.keys()),
        'supported_generation_options': {
            'speed': 'unsupported by Chatterbox-Turbo generate()',
            'temperature': {'default': 0.8, 'min': 0.05, 'max': 2.0},
            'top_p': {'default': 0.95, 'min': 0.05, 'max': 1.0},
            'top_k': {'default': 1000, 'min': 1, 'max': 2000},
            'repetition_penalty': {'default': 1.2, 'min': 1.0, 'max': 2.0},
            'postprocess_audio': 'leading/trailing trim plus mild low-energy inter-phrase attenuation',
        },
        'production_tts_changed': True,
    }


@app.get('/v1/audio/voices')
def voices():
    return {
        'default': 'talon-elegant',
        'recommended': sorted(presets.keys()),
        'aliases_active': active_aliases,
        'aliases_pending_final_approval': pending_aliases,
        'data': [
            {
                'id': name,
                'object': 'voice',
                'persona': preset.get('persona'),
                'source_candidate': preset.get('source_candidate'),
                'reference_sha256': preset.get('reference_sha256'),
            }
            for name, preset in sorted(presets.items())
        ],
    }


@app.get('/v1/models')
def models():
    return {'data': [{'id': 'chatterbox-turbo', 'object': 'model', 'owned_by': 'nest'}]}


@app.post('/v1/audio/speech')
def speech(request: SpeechRequest):
    if request.response_format != 'wav':
        raise HTTPException(status_code=400, detail='Only wav response_format is currently supported')
    if request.model not in ('chatterbox-turbo', 'chatterbox'):
        raise HTTPException(status_code=400, detail='Only chatterbox-turbo model is currently supported')
    validate_generation_options(request)
    preset_name, preset = resolve_voice(request.voice)
    reference = PRESET_ROOT / preset_name / 'reference.wav'
    if not reference.exists():
        raise HTTPException(status_code=500, detail=f'Reference audio missing for {preset_name}')
    if sha256(reference) != preset.get('reference_sha256'):
        raise HTTPException(status_code=500, detail=f'Reference audio SHA256 mismatch for {preset_name}')
    input_text = normalize_for_tts(request.input) if request.normalize else request.input
    started = time.perf_counter()
    postprocess = {'enabled': False}
    with lock:
        tts = get_model()
        tts.conds = get_conditionals(tts, preset_name, reference)
        audio = tts.generate(
            input_text,
            audio_prompt_path=None,
            norm_loudness=False,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k,
            repetition_penalty=request.repetition_penalty,
        )
    elapsed = time.perf_counter() - started
    data = audio_to_float32(audio)
    if request.postprocess_audio:
        data, postprocess = postprocess_audio(data, tts.sr)
    content, duration = write_wav(data, tts.sr)
    headers = {
        'X-Nest-TTS-Provider': 'chatterbox-turbo',
        'X-Nest-TTS-Voice': preset_name,
        'X-Nest-TTS-Normalized': str(request.normalize).lower(),
        'X-Nest-TTS-Norm-Loudness': 'false',
        'X-Nest-TTS-Temperature': f'{request.temperature:.3f}',
        'X-Nest-TTS-Top-P': f'{request.top_p:.3f}',
        'X-Nest-TTS-Top-K': str(request.top_k),
        'X-Nest-TTS-Repetition-Penalty': f'{request.repetition_penalty:.3f}',
        'X-Nest-TTS-Postprocess': json.dumps(postprocess, sort_keys=True),
        'X-Nest-TTS-Seconds': f'{duration:.3f}',
        'X-Nest-TTS-Wall-Seconds': f'{elapsed:.3f}',
        'X-Nest-TTS-RTF': f'{elapsed / duration:.3f}' if duration else '0',
    }
    return Response(content=content, media_type='audio/wav', headers=headers)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
