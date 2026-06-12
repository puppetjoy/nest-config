# Hermes OpenAI Codex native credential rotation

Joy's Hermes agent team uses Hermes' native `openai-codex` credential pool instead of the retired Nest slot-switcher helper.

## Steady-state policy

- Store the primary and secondary Codex OAuth credentials in Hermes' native credential pool in the shared root Hermes home (`~/.hermes/auth.json`).
- Label the entries `primary` and `secondary`.
- Keep `primary` at priority `0` and `secondary` at priority `1`.
- Use the native `fill_first` rotation strategy so Hermes spends primary first, rotates to secondary when primary is rate-limited/exhausted, and returns to primary after its cooldown clears.
- Keep profile-local `openai-codex` credentials absent from `~/.hermes/profiles/<profile>/auth.json` so Talon, Star, and future profiles all read the shared root pool.

Hermes' credential-pool docs are the source of truth for runtime behavior: same-provider pool entries are tried before fallback providers, usage-limit 429s rotate immediately, transient 429s retry once before rotation, billing/quota errors rotate with a longer cooldown, and OAuth 401s try refresh before rotating.

## Owner-operated login workflow

Use Hermes' native auth command from Joy's trusted shell, normally against the shared root Hermes home:

```sh
hermes auth add openai-codex --type oauth --label primary --no-browser
hermes auth add openai-codex --type oauth --label secondary --no-browser
```

Open the printed Codex device URL in the owner-operated OAuth browser or Joy's local private/incognito browser and enter the public device code. Joy handles account selection, passwords, passkeys, 2FA, CAPTCHA, and consent directly in the browser.

Do not paste token JSON, callback URLs containing codes, browser cookies/storage, passwords, passkeys, or 2FA codes into chat, tickets, Kanban comments, commits, logs, or memory.

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
python3 - <<'PY'
import json
from pathlib import Path
for label, path in {
    'root': Path.home() / '.hermes/auth.json',
    'talon': Path.home() / '.hermes/profiles/talon/auth.json',
    'star': Path.home() / '.hermes/profiles/star/auth.json',
}.items():
    data = json.loads(path.read_text()) if path.exists() else {}
    entries = data.get('credential_pool', {}).get('openai-codex', [])
    provider = 'openai-codex' in data.get('providers', {})
    print(label, {'provider_entry': provider, 'pool_entries': len(entries)})
PY
```

Root should have two pool entries. Profiles should have zero `openai-codex` pool entries and no provider entry.

## Recovery

- If a credential is exhausted but should be retried now, use `hermes auth reset openai-codex`.
- If a credential was captured against the wrong OpenAI account, remove it with `hermes auth remove openai-codex <index|id|label>` and re-add it with the correct label.
- If a profile-local reauth accidentally shadows the shared pool, remove only that profile's `openai-codex` provider/pool entries or re-run the profile shadow check and cleanup. Do not copy token JSON through chat.
- If the shared root pool is lost, re-add `primary` and `secondary` with native `hermes auth add openai-codex --type oauth --label ...`.

## Retired helper

The former Nest-managed `hermes-codex-auth` / `hermes-share-codex-auth` slot switcher and `~/.hermes/codex-auth/slots.json` store are intentionally retired. Puppet removes those helper commands and the legacy slot directory so native Hermes pool rotation remains the only steady-state mechanism.
