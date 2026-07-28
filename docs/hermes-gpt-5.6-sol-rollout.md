# Hermes gpt-5.6-sol rollout

Talon inherits the `nest::app::hermes` default model. Star has an explicit
instance override in `data/host/owl.yaml`; both are set to
`openai-codex/gpt-5.6-sol`. Compression, web extraction, and title generation
remain pinned to `openai-codex/gpt-5.4-mini`.

Apply the normal Puppet control-repo deployment, then run Puppet on `owl`.
Verify Talon before Star so the two profile gateways are not deliberately
restarted together. A new session is required to prove the startup model;
existing sessions can retain the model selected when they started.

## Rollback

Revert `model_name` to `gpt-5.5` in these source locations and repeat the same
deploy/apply/verification sequence:

- `manifests/app/hermes.pp`, the application-wide default;
- `manifests/lib/hermes.pp`, the profile define default;
- `data/host/owl.yaml`, Star's explicit instance override.

Do not change the `openai-codex` provider, Codex base URL, or the
`gpt-5.4-mini` auxiliary task settings during model rollback.

The pre-rollout live profile backups from the initial manual canary are:

- `/home/joy/.hermes/profiles/talon/config.yaml.bak-gpt-5.6-sol-20260728-142801`
- `/home/joy/.hermes/profiles/star/config.yaml.bak-gpt-5.6-sol-20260728-142801`

Those files are emergency evidence only. Source rollback plus Puppet apply is
the durable recovery path.