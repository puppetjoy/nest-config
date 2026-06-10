# Kokoro pivot artifacts for t_e1069dd0

Generated from live owl services on 2026-06-10 while preparing the Talon/Star Hermes TTS pivot from Chatterbox to `voice-speech` Kokoro.

## Source prompts

- `prompts/received.txt`: structured received phrasing with task/request IDs
- `prompts/review_ready.txt`: review-ready phrasing with Nest ops terms and a commit hash
- `prompts/blocked.txt`: blocked phrasing with a local path and URL

## Audio sets

- `chatterbox-before/`: current production Chatterbox endpoint `http://10.108.157.193`
- `kokoro-after/`: Kokoro comparison samples from `voice-speech` endpoint `http://10.108.246.221`
  - Talon comparison: `af_heart`
  - Star: `af_nova`
- `voice-grid/`: Joy-selected Talon Kokoro probe `af_alloy`

All files are WAV, mono, 24 kHz. `manifest.json` contains wall time, duration, RTF, byte size, and SHA-256 for each generated sample.

## Timing summary

From the generated manifest:

- Chatterbox before: 6 samples, average wall 14.773s, average RTF 0.915, max wall 19.694s
- Kokoro after/all grid samples: 9 samples, average wall 1.717s, average RTF 0.122, max wall 2.206s
- Selected Talon `af_alloy`: average wall 1.784s, average RTF 0.131
- Proposed Star `af_nova`: average wall 1.309s, average RTF 0.101
- Previous Talon `af_heart` comparison: average wall 2.057s, average RTF 0.133

Health evidence at generation time:

- `voice-speech`: HTTP 200, version `0.3.0`, Kokoro `0.9.4`, PyTorch `2.9.1+rocm7.2.4`, device `Radeon 8060S Graphics`, cached voices `af_alloy`, `af_heart`, `af_nova`
- `voice-chatterbox`: HTTP 200, version `0.1.2`, aliases `talon -> talon-elegant`, `star -> star-clear`

## Notes

These artifacts prove raw endpoint speed/format and provide listening samples. Final acceptance still needs the reviewed source applied through Puppet and a real Telegram Agent Request voice notification from the broker/Hermes path.
