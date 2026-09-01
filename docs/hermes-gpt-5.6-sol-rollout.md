# Hermes gpt-5.6-sol rollout

Talon inherits the `nest::app::hermes` default model. Star has an explicit
instance override in `data/host/owl.yaml`; both are set to
`openai-codex/gpt-5.6-sol`. The shared auxiliary policy uses
`openai-codex/gpt-5.6-terra` for compression fallback and web extraction, and
`openai-codex/gpt-5.6-luna` for title generation. Beryl and provisional Quill
inherit the same auxiliary policy even when their primary models differ.

The deployed Hermes source is pinned to the merged v0.21.0-based Nest fork at
`58185e349a24f12c9c9e74e3d66aa34b47b2fd47` on the `nest` branch. The previous
known-good rollback commit is
`ed28eb62c23f85b71d629de67c1a77f4ae7fdecd`.

Apply the normal Puppet control-repo deployment, then run Puppet on `owl`.
Canary Star first, then Beryl, then Talon. A new session is required to prove
the startup model; existing sessions can retain the model selected when they
started. Verify lightweight Telegram streaming, tool execution, session
resume, the native Responses compaction path, Terra fallback behavior, and
Luna title generation through each profile's real runtime.

## Rollback

For a Hermes v0.21.0 runtime regression, change
`nest::app::hermes::git_commit` in `data/host/owl.yaml` to the known-good
rollback commit above and repeat the normal deploy/apply/verification
sequence. Keep `git_ref: nest` so Puppet verifies the rollback commit remains
reachable from the managed branch.

For a primary-model-only rollback, revert `model_name` to `gpt-5.5` in these
source locations and repeat the same sequence:

- `manifests/app/hermes.pp`, the application-wide default;
- `manifests/lib/hermes.pp`, the profile define default;
- `data/host/owl.yaml`, Star's explicit instance override.

Do not change the `openai-codex` provider, Codex base URL, or Terra/Luna
auxiliary task settings during a primary-model-only rollback. If an auxiliary
model itself causes the regression, roll back the three task-specific model
parameters together so compression, web extraction, and title generation
remain explicit and independently reviewable.

The pre-rollout live profile backups from the initial manual canary are:

- `/home/joy/.hermes/profiles/talon/config.yaml.bak-gpt-5.6-sol-20260728-142801`
- `/home/joy/.hermes/profiles/star/config.yaml.bak-gpt-5.6-sol-20260728-142801`

Those files are emergency evidence only. Source rollback plus Puppet apply is
the durable recovery path.