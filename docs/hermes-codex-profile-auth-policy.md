# Hermes OpenAI Codex auth across profiles

Hermes source still treats named profiles as independent homes. A profile such
as `talon` or `star` resolves `HERMES_HOME` to
`~/.hermes/profiles/<profile>`, so an interactive command such as
`hermes -p star auth add openai-codex` writes Star's profile-local
`auth.json`. Reads are more flexible: provider state and credential-pool
entries fall back to the root `~/.hermes/auth.json` when the active profile has
no local entry for that provider.

Source evidence:

- `hermes_cli/profiles.py` describes each named profile as its own
  `HERMES_HOME` under `~/.hermes/profiles/<name>/`.
- `hermes_cli/auth.py` writes auth through `get_hermes_home() / "auth.json"`.
- `_load_provider_state()` and `read_credential_pool()` read from the root
  auth store only when a profile has no local entry for the requested provider.
- `hermes_cli/auth_commands.py` implements `auth add openai-codex` by running
  the Codex device-code flow and saving tokens for the active profile.

## Nest policy

Joy's Hermes agent team shares one OpenAI Codex auth state. Nest enforces that
policy by using Hermes' existing root-auth fallback deliberately:

1. Keep the shared Codex provider and credential-pool entries in
   `~/.hermes/auth.json`.
2. Remove only the `openai-codex` provider and credential-pool entries from
   each managed profile's `auth.json`.
3. Leave profile-local non-Codex auth, API keys, config, memories, skills,
   sessions, and other runtime state alone.

With the profile-local Codex entries removed, Talon, Star, and future managed
profiles all read the same root Codex auth state. This avoids copying tokens in
chat and avoids silently diverging quota/exhaustion caches between profiles.

Puppet installs `/opt/hermes-agent/bin/hermes-share-codex-auth` and runs it from
`nest::app::hermes::config` as Joy. The script does not print token values. On
apply it chooses the freshest non-exhausted available `openai-codex` entry from
the root or managed profiles, writes that entry to the root auth store, and
removes profile-local `openai-codex` entries that would shadow the shared root
state. If a future interactive reauth is accidentally run with `-p talon` or
`-p star`, the next Puppet run migrates that fresh profile credential back to
the shared root store.

## Operator workflow

Preferred reauth target:

```sh
hermes auth add openai-codex
```

That command should be run from Joy's trusted shell without `-p`, so it writes
the root auth store directly. Do not paste tokens, `auth.json` contents,
callback URLs containing codes, or browser secrets into chat or tickets.

If a profile-specific reauth has already happened, do not manually copy tokens.
Run Puppet so the managed sharing policy migrates the fresh profile-local Codex
entry into the shared root store and removes local shadow entries:

```sh
sudo puppet agent --test
sudo puppet agent --test
```

After a reauth or Puppet migration, restart long-running profile services so
running gateways/dashboard sessions reload the shared auth state:

```sh
systemctl --user restart hermes-gateway@talon.service hermes-dashboard@talon.service
systemctl --user restart hermes-gateway@star.service hermes-dashboard@star.service
```

The Puppet-managed restart hooks also refresh those services when the Codex
sharing exec changes auth state during a managed apply.

## Status checks

`hermes -p <profile> auth status openai-codex` proves only that Hermes can see a
credential. It can still print `logged in` when the cached pool entry is
rate-limited or exhausted.

Use both presence and quota/exhaustion checks for every affected profile:

```sh
hermes -p talon auth list openai-codex
hermes -p talon auth status openai-codex
hermes -p star auth list openai-codex
hermes -p star auth status openai-codex
```

`auth list` is the quota/exhaustion-oriented check. It surfaces cached
`rate-limited`, `usage_limit`, `quota`, `exhausted`, error code, and wait-window
metadata on each pool entry. `auth status` remains useful as a credential
presence check but is not enough by itself.

For source-level verification of the sharing policy, check only non-secret
structure:

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
    print(label, {
        'provider_entry': 'openai-codex' in data.get('providers', {}),
        'pool_entry': 'openai-codex' in data.get('credential_pool', {}),
    })
PY
```

Expected managed state: root has both entries; managed profiles do not. The
profile CLI commands above should still show Codex auth because Hermes falls
back to the shared root store.

## Current incident notes

During the June 2026 Talon/Star divergence, Talon had a refreshed local Codex
credential while Star still had a local pool entry carrying `last_status =
exhausted`, `last_error_code = 429`, and `last_error_reason =
usage_limit_reached`. Star recovered only after Joy reauthed Star directly. The
managed policy above prevents that class of divergence by making profile-local
Codex entries temporary migration sources rather than steady-state auth stores.
