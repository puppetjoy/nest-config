# Hermes OpenAI Codex native credential rotation

Joy's Hermes agent team uses Hermes' native `openai-codex` credential pool as runtime-owned state. Puppet manages the safe/static pieces around that state: file ownership, helper tooling, shared-profile policy, service wiring, and removal of retired slot-switcher artifacts. Puppet must not store, render, or continuously re-apply raw Codex OAuth access or refresh tokens.

## Steady-state policy

- Store the primary and secondary Codex OAuth credentials in Hermes' native credential pool in the shared root Hermes home (`~/.hermes/auth.json`).
- Label the entries `primary` and `secondary`.
- Keep `primary` at priority `0` and `secondary` at priority `1`.
- Use the native `fill_first` rotation strategy so Hermes spends primary first, rotates to secondary when primary is rate-limited/exhausted, and returns to primary after its cooldown clears.
- Keep profile-local `openai-codex` credentials absent from `~/.hermes/profiles/<profile>/auth.json` so Talon, Star, and other approved Codex profiles read the shared root pool.
- Keep local-model profiles such as Beryl governed by their configured model/provider policy; do not add profile-local Codex token shadows for them.

Hermes' credential-pool docs are the source of truth for runtime behavior: same-provider pool entries are tried before fallback providers, usage-limit 429s rotate immediately, transient 429s retry once before rotation, billing/quota errors rotate with a longer cooldown, and OAuth 401s try refresh before rotating.

## Owner-operated login workflow

Use Hermes' native auth command from Joy's trusted shell, normally against the shared root Hermes home:

```sh
hermes auth add openai-codex --type oauth --label primary --no-browser
hermes auth add openai-codex --type oauth --label secondary --no-browser
```

Open the printed Codex device URL in the owner-operated secure browser (using the OAuth/device-flow tools) or Joy's local private/incognito browser and enter the public device code. Joy handles account selection, passwords, passkeys, 2FA, CAPTCHA, and consent directly in the browser.

Do not paste token JSON, callback URLs containing codes, browser cookies/storage, passwords, passkeys, or 2FA codes into chat, tickets, Kanban comments, commits, logs, or memory.

If one credential must be rotated, remove or replace only that native pool entry:

```sh
hermes auth list openai-codex
hermes auth remove openai-codex <index|id|label>
hermes auth add openai-codex --type oauth --label <primary|secondary> --no-browser
```

Puppet does not carry an encrypted backup copy of the OAuth tokens anymore, so normal runtime backup/restore of `~/.hermes/auth.json` is the preferred recovery source. If that backup is missing or stale, explicitly re-authenticate the missing `primary` and/or `secondary` entries with the commands above instead of resurrecting old token JSON from Hiera.

## Rotation strategy

`fill_first` is Hermes' default, but it is safe to make it explicit through the interactive wizard:

```sh
hermes auth
# 4. Set rotation strategy for a provider
# provider: openai-codex
# strategy: fill_first
```

Equivalent config shape:

```yaml
credential_pool_strategies:
  openai-codex: fill_first
```

## Verification

Safe native status checks:

```sh
hermes auth list openai-codex
hermes -p talon auth list openai-codex
hermes -p star auth list openai-codex
```

Expected output shape:

```text
openai-codex (2 credentials):
  #1  primary    oauth  device_code ←
  #2  secondary  oauth  device_code
```

`auth list` is the quota/exhaustion-oriented check; it surfaces `rate-limited`, `usage_limit`, `quota`, `exhausted`, error-code, and wait-window metadata. `auth status` can prove that Hermes sees a credential, but it is less useful for rotation decisions.

Profile shadow check without printing secrets:

```sh
/opt/hermes-agent/bin/hermes-manage-codex-pool status --home /home/joy talon star beryl
/opt/hermes-agent/bin/hermes-manage-codex-pool check --home /home/joy talon star beryl
```

`status` prints a redacted root-pool summary plus profile shadow counts. `check` exits non-zero only when one of the named profiles has a profile-local `openai-codex` provider or pool shadow. It does not compare root token material against Puppet and does not fail merely because a credential is missing; use `hermes auth list openai-codex` for root credential health and quota/exhaustion state.

Expected shape: root has the intentionally live pool entries, Talon and Star can see them through Hermes' shared root-pool lookup, and Talon/Star/Beryl profile auth files have zero local `openai-codex` pool entries and no provider entry.

## Puppet-managed guardrails

Puppet intentionally keeps only safe/static guardrails:

- the Hermes home and profile directories;
- the `hermes-manage-codex-pool` helper;
- removal of the retired `~/.hermes/codex-auth` slot-switcher state;
- absence of the former `~/.hermes/openai-codex-pool.json` Puppet payload file;
- profile-shadow cleanup with `hermes-manage-codex-pool apply --home /home/joy talon star beryl`.

The helper's `apply` mode removes profile-local Codex shadows only. It never writes root `credential_pool.openai-codex` entries and never reads token JSON from Puppet/Hiera.

## Recovery

- If a credential is exhausted but should be retried now, use `hermes auth reset openai-codex`.
- If a credential was captured against the wrong OpenAI account, remove it with `hermes auth remove openai-codex <index|id|label>` and re-add it with the correct label.
- If a profile-local reauth accidentally shadows the shared pool, run `/opt/hermes-agent/bin/hermes-manage-codex-pool apply --home /home/joy talon star beryl` or remove only that profile's `openai-codex` provider/pool entries. Do not copy token JSON through chat.
- If the shared root pool is lost and runtime backups cannot restore it, re-add `primary` and `secondary` with native `hermes auth add openai-codex --type oauth --label ...`.

## Retired helpers

The former Nest-managed `hermes-codex-auth` / `hermes-share-codex-auth` slot switcher, `~/.hermes/codex-auth/slots.json` store, and Puppet-rendered `~/.hermes/openai-codex-pool.json` payload are intentionally retired. Native Hermes pool rotation is the only steady-state credential mechanism.
