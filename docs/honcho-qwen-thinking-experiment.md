# Honcho Qwen thinking synthesis experiment

This repo intentionally keeps Honcho's local-Qwen thinking disabled on hot paths while testing a narrow synthesis-heavy exception.

## Intervention

- id: `qwen-thinking-dream-synthesis-v1`
- active paths: dream deduction and dream induction specialists
- no-thinking paths: routine deriver representation batches, summaries, and all dialectic levels (`minimal`, `low`, `medium`, `high`, and `max`)
- limiter topology: unchanged; Honcho still reaches Qwen through the two-request `llama-qwen-honcho` limiter
- output safety: unchanged; length-finished partial output remains rejected instead of being recorded as durable memory

The Kubernetes env values are strings because container environment variables are strings. The maintained Honcho fork normalizes known OpenAI-compatible `chat_template_kwargs.enable_thinking` provider params at the OpenAI request boundary so outgoing JSON carries booleans (`true`/`false`), not string values (`"true"`/`"false"`).

## Hourly eval awareness

The hourly self-improvement/eval loop should tag rows and notes with the intervention id when this config is deployed. New thinking-token cost is not automatically bad; compare quality movement against budget and reliability.

Track content-safe aggregate changes in these classes:

- recall relevance and usefulness
- useful dream observation/conclusion yield
- noise, duplicate, or stale-memory movement
- `finish_reason='length'` counts
- controlled `IncompleteLLMOutputError` counts
- tool-loop max-iteration warnings
- limiter 400/503/timeout counts and active/cap shape
- prompt/completion/total token distributions
- queue latency and active work cleanup

If live eval tooling reads the deployed Honcho pod or deployment environment, it can use:

- `HONCHO_THINKING_INTERVENTION_ID=qwen-thinking-dream-synthesis-v1`
- `HONCHO_THINKING_INTERVENTION_PATHS=dream_deduction,dream_induction`
- `HONCHO_THINKING_INTERVENTION_EVAL_NOTE=...`

## Rollback criteria

Rollback to no-thinking on dream specialists if recent post-deploy evidence shows material regressions in length/truncation, tool-loop, limiter pressure, queue latency, or failed/no-observation dream cycles without a matching improvement in relevance, recall usefulness, or useful observation yield.

Do not schedule or induce extra dreams from the hourly loop for this experiment. Manual dream tests require separate explicit approval.
