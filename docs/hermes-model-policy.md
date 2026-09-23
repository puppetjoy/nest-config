# Hermes model policy

The Owl Hermes profiles use explicit primary-model assignments:

- Talon: `openai-codex/gpt-6-sol`
- Star: `openai-codex/gpt-6-astra`
- Quill: `copilot/gpt-6-luna` with `agent.reasoning_effort: max` and
  `model.api_mode: codex_responses`
- Beryl: `custom:llama-qwen/qwen-3.6`

Talon and Star inherit the shared hosted helper policy. Compression fallback,
web extraction, title generation, and delegated children all use
`openai-codex/gpt-6-luna`. Quill explicitly uses `copilot/gpt-6-luna` for the
same helper and delegation routes so its employer-owned Copilot credential
boundary remains intact. Helper and delegation routes do not set a reasoning
effort; they use each provider/model default. Quill's main-route `max` setting
must not be copied into auxiliary or delegation configuration.

Beryl is deliberately isolated from the hosted GPT policy. Its per-instance
auxiliary and delegation overrides keep primary inference, compression, web
extraction, title generation, and delegated children entirely on
`custom:llama-qwen/qwen-3.6`. New local-only profiles must set every auxiliary
and delegation override rather than inheriting the application defaults.

The deployed Hermes source follows the managed `nest` branch or its temporary
source-managed commit pin. Apply changes with the normal Puppet control-repo
deployment, then run Puppet on `owl`. Existing sessions can retain the model
selected when they started, so restart or switch each affected gateway only
after confirming there is no active turn.

After deployment, read both managed and effective configuration for Talon,
Star, and Quill. Verify the primary provider/model pair, all four helper and
delegation routes, Quill's Responses API mode and main-route max reasoning,
and the absence of helper/delegation reasoning overrides. Run a new-session
primary canary for each affected profile and at least one real hosted helper or
delegated-child canary. Confirm Telegram and dashboard continuity. For Quill,
also prove that its provider remains Copilot and no personal Codex credential
pool is inherited.

## Rollback

Use source rollback plus the normal deploy/apply sequence; do not rely on a
profile-local overlay. A primary-only rollback must keep provider and credential
boundaries unchanged. A helper-only rollback should change all four helper and
delegation model values together for the affected provider while retaining
provider-default reasoning. Beryl's local routes must remain unchanged in every
rollback.
