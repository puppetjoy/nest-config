# Owl voice-speech TTS maintenance notes

The Eyrie `ai/voice-speech` service is the current local speech boundary for
Talon and Star. It provides Kokoro TTS at `/v1/audio/speech` and Whisper STT at
`/v1/audio/transcriptions` from the source-managed KubeCM app in
`data/kubernetes/app/voice-speech.yaml`.

## Maintained behavior

- Kokoro remains the selected production TTS model for Talon/Star local voice
  notifications after the cadence experiment rollback.
- Hermes owns rich speech normalization before command-provider TTS calls. The
  Puppet-managed `hermes-voice-speech-tts` wrapper and service-side
  `normalize_for_tts` logic are only fallback safety nets for direct calls.
- Fallback normalization must not read low-value operational tokens literally:
  `ar-*`, `rva-*`, `t_*`, hashes, checksums, long commit IDs, URLs, and
  slash-heavy paths should be summarized for speech.
- Visual Telegram/Markdown notification text is not changed by this layer.

## Removed experiment surfaces

The Chatterbox/Kokoro comparison audio grid and cadence-tuning artifact tree were
removed from source. They were useful review artifacts during the rejected
cadence/onset/pause experiments, but they are not part of the long-lived
maintained TTS system.

The Nest voice-speech fallback normalizer no longer performs colon/semicolon
pause rewrites. Cadence-specific rewriting belongs in the reviewed Hermes speech
normalization path, not in a second Puppet-managed command wrapper or service
fallback.

## Verification pattern

For source-only maintenance changes, run the focused wrapper tests:

```sh
python3 spec/app/hermes/test_voice_speech_tts_command.py
```

For an approved deploy, render/deploy the KubeCM service through the normal
`nest::eyrie::ai::deploy_voice_speech` plan, restart affected Hermes gateways if
profile config changed, and verify a real TTS request through the configured
`voice-speech` endpoint.
