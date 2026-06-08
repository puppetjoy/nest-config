# Hermes OpenAI Codex auth slots across profiles

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

Joy's Hermes agent team has two owner-operated OpenAI Codex OAuth
subscriptions, labelled `primary` and `secondary`. Nest keeps both token sets
as private/encrypted Puppet data, then activates exactly one slot into Hermes'
root auth fallback store:

1. Joy completes each OAuth/device-code flow locally. Do not paste token JSON,
   callback URLs containing codes, browser cookies, or any other token material
   into chat, Kanban comments, tickets, commits, logs, or memory.
2. Joy captures the resulting `openai-codex` provider and credential-pool
   payload as a labelled slot and stores each slot as an encrypted value in
   `nest/private` Hiera under `nest::app::hermes::codex_oauth_slots`.
3. Puppet renders the decrypted private values to
   `~/.hermes/codex-auth/slots.json` with mode `0600` and `show_diff => false`.
4. `/opt/hermes-agent/bin/hermes-codex-auth` activates the selected slot by
   writing only that slot's `openai-codex` provider and pool entries to the
   shared root `~/.hermes/auth.json`.
5. The same helper removes only profile-local `openai-codex` entries from
   managed profiles so Talon, Star, and future managed profiles use the shared
   root fallback instead of stale profile-local quota caches.

The runtime selected label is `~/.hermes/codex-auth/active-label`. Puppet
creates it only if missing, seeded from
`nest::app::hermes::codex_oauth_default_label` (default `primary`), and does
not replace it. Manual or chat-approved switches therefore survive later Puppet
runs while still using the Puppet-private slot store.

If no private slot store exists yet, the helper preserves the legacy migration
behavior: it chooses the freshest non-exhausted local/root `openai-codex` state,
writes it to the root auth store, and removes profile-local shadows.

## Shared OAuth browser workflow

Joy can complete login and consent in a persistent Kasm browser that Talon can
also navigate and inspect at a redacted metadata level. The browser is deployed
as the `ai/oauth-browser` KubeCM service at `https://oauth-browser.eyrie/`, with
a PVC-backed Chrome profile and Bitwarden extension policy like the shopping
browser, but with a narrower Hermes `oauth_browser` toolset.

Talon may use `oauth_browser_login_prompt` or `oauth_browser_navigate` to open a
provider/device-code URL in that browser and produce an owner-facing prompt.
Joy then uses the Kasm UI to unlock Bitwarden, sign in, satisfy passkeys, 2FA,
CAPTCHA, and approve consent. Talon must not request or receive passwords,
passkeys, 2FA codes, callback URLs containing `code=`, browser cookies, local
storage, raw screenshots of secret pages, or token JSON in chat/tool output.

Treat account identity as part of the OAuth safety boundary. A persistent shared
browser can silently reuse the wrong provider account even when the CLI/device
code flow reports success. Before using the shared OAuth browser for a second
OpenAI account, Joy should explicitly sign out or confirm the intended account
in the browser UI. If the provider does not make the active account unmistakable,
prefer Joy's local private/incognito browser for that account and use Talon only
for the redacted capture/status/fingerprint steps.

Safe status commands for the shared browser:

```sh
hermes -p talon chat -q 'Check oauth_browser_status with include_page=true and report only redacted origin/title/readiness.'
kubectl -n ai get deploy/oauth-browser,svc/oauth-browser,ingress/oauth-browser,pvc/oauth-browser-profile
```

The OAuth browser bridge reports the public Kasm URL, Kubernetes readiness,
redacted origin/path/title/query-key names, and whether a URL fragment is
present. It does not return visible page text, raw DOM, cookies, storage,
headers, CDP endpoints, or callback codes. Use the normal Hermes auth/capture
commands below only after Joy reports that the owner-operated browser flow has
completed.

## Owner-operated capture workflow

Run the OAuth flow from Joy's trusted shell. Prefer root/default Hermes auth so
capture source is unambiguous:

```sh
hermes auth add openai-codex
```

Before overwriting private Hiera, compare the fresh local capture source against
any already-rendered managed slots. This command prints only labels, counts, and
a redacted fingerprint; if `matches_existing_slots` names the wrong label, stop
and redo the owner-operated login in a browser/account context that clearly uses
the intended account:

```sh
/opt/hermes-agent/bin/hermes-codex-auth fingerprint --home /home/joy
```

Capture the result as encrypted EYAML output. The helper pipes plaintext JSON
directly to the local `eyaml encrypt --stdin` process and prints only the
encrypted block:

```sh
/opt/hermes-agent/bin/hermes-codex-auth capture primary \
  --eyaml-label 'nest::app::hermes::codex_oauth_slots.primary'
```

Repeat the OAuth flow and capture for `secondary`:

```sh
hermes auth add openai-codex
/opt/hermes-agent/bin/hermes-codex-auth fingerprint --home /home/joy
/opt/hermes-agent/bin/hermes-codex-auth capture secondary \
  --eyaml-label 'nest::app::hermes::codex_oauth_slots.secondary'
```

Place each encrypted block in the private Hiera value as a per-slot encrypted
string:

```yaml
nest::app::hermes::codex_oauth_slots:
  primary: >
    ENC[PKCS7,...]
  secondary: >
    ENC[PKCS7,...]
```

Each decrypted value is the JSON object emitted by the matching `capture`
command. Edit the private Hiera file using the existing Nest private/eyaml
workflow so the committed private repo contains only `ENC[PKCS7,...]` blocks,
not plaintext JSON. If a temporary plaintext file is ever used with
`capture --out`, keep it on a trusted local filesystem, remove it immediately
after encrypting, and never commit it.

After updating private Hiera, deploy/apply Puppet through the normal reviewed
Nest workflow. The public repo only defines the parameter, file paths, modes,
and helper behavior; the token material belongs in `nest/private`.

## Chat-driven switch path

When Joy asks Talon/Star to switch subscriptions, the agent should use the
normal approval/review path before touching live credentials or restarting
services. The side effect to approve is:

```sh
/opt/hermes-agent/bin/hermes-codex-auth switch secondary \
  --home /home/joy \
  --slots-file /home/joy/.hermes/codex-auth/slots.json \
  --active-file /home/joy/.hermes/codex-auth/active-label \
  --restart talon star
```

Use `primary` instead of `secondary` to switch back. The command prints only the
activated label, cleaned profile names, and service-unit names; it does not
print token values. `--restart` reloads the long-running gateway/dashboard units
so new agent sessions use the selected credential reliably.

## CLI/manual switch path

If the active subscription is exhausted and Joy needs to switch without relying
on a running agent session, run the same command from a trusted shell:

```sh
/opt/hermes-agent/bin/hermes-codex-auth switch secondary \
  --home /home/joy \
  --slots-file /home/joy/.hermes/codex-auth/slots.json \
  --active-file /home/joy/.hermes/codex-auth/active-label \
  --restart talon star
```

If systemd restart fails because the user manager is unavailable, switch first
without `--restart`, then restart the units when the user manager is reachable:

```sh
systemctl --user try-reload-or-restart \
  hermes-gateway@talon.service hermes-dashboard@talon.service \
  hermes-gateway@star.service hermes-dashboard@star.service
```

Puppet also subscribes the Talon/Star service restart hooks to the Codex auth
sharing exec, so a managed apply refreshes services when the helper changes the
active root auth state.

## Status and verification

Redacted fingerprint check for the current local capture source:

```sh
/opt/hermes-agent/bin/hermes-codex-auth fingerprint --home /home/joy
/opt/hermes-agent/bin/hermes-codex-auth fingerprint --home /home/joy --from-profile talon
```

The fingerprint mode reads the same root/profile auth source that `capture` would
use and reports whether that fresh source matches any existing managed slot. It
is the pre-overwrite gate for account-switch-sensitive captures.

Safe redacted status from the managed slot store:

```sh
/opt/hermes-agent/bin/hermes-codex-auth status \
  --home /home/joy \
  --slots-file /home/joy/.hermes/codex-auth/slots.json \
  --active-file /home/joy/.hermes/codex-auth/active-label \
  talon star
```

The JSON status includes labels, active label, provider/pool presence, pool
entry counts, exhausted-entry counts, non-secret fingerprints, and any
profile-local Codex shadows. It never includes token values.

Hermes' own status commands are still useful, but interpret them carefully:

```sh
hermes -p talon auth list openai-codex
hermes -p talon auth status openai-codex
hermes -p star auth list openai-codex
hermes -p star auth status openai-codex
```

`auth status` proves only that Hermes can see a credential. It can still print
`logged in` when the cached pool entry is rate-limited or exhausted. `auth list`
is the quota/exhaustion-oriented check and surfaces cached `rate-limited`,
`usage_limit`, `quota`, `exhausted`, error-code, and wait-window metadata.

Source-level structure check without token output:

```sh
python3 - <<'PY'
import json
from pathlib import Path
for label, path in {
    'root': Path.home() / '.hermes/auth.json',
    'talon': Path.home() / '.hermes/profiles/talon/auth.json',
    'star': Path.home() / '.hermes/profiles/star/auth.json',
    'slots': Path.home() / '.hermes/codex-auth/slots.json',
    'active': Path.home() / '.hermes/codex-auth/active-label',
}.items():
    if label == 'active':
        print(label, path.read_text().strip() if path.exists() else None)
        continue
    data = json.loads(path.read_text()) if path.exists() else {}
    print(label, {
        'provider_entry': 'openai-codex' in data.get('providers', {}),
        'pool_entry': 'openai-codex' in data.get('credential_pool', {}),
        'slot_labels': sorted(data.get('slots', {}).keys()) if label == 'slots' else None,
    })
PY
```

Expected managed state: `slots` has `primary` and `secondary`, root has the
selected slot's Codex entries, managed profiles do not have local Codex entries,
and the profile CLI commands still show Codex auth because Hermes falls back to
the shared root store.

## Recovery and rollback

- Switch rollback: run `hermes-codex-auth switch primary ... --restart talon
  star` (or `secondary`) to reactivate the prior subscription.
- Bad active marker: replace `~/.hermes/codex-auth/active-label` with a known
  slot label, mode `0600`, then run `hermes-codex-auth apply ... talon star` or
  Puppet.
- Bad private slot JSON: revert the private Hiera commit and rerun the normal
  Puppet deploy/apply. The helper refuses unknown labels and invalid slot JSON
  before rewriting root auth.
- Accidental profile-local reauth: do not manually copy token JSON. Run
  `hermes-codex-auth apply ... talon star` or Puppet; legacy mode migrates the
  freshest profile-local Codex state to root, and slot mode removes local
  shadows so they cannot mask the active slot.
- Lost root auth file: rerun `hermes-codex-auth apply ... talon star`; it
  reconstructs the selected `openai-codex` entries from the private slot store.
- Lost private slot store: recapture both subscriptions from fresh OAuth flows
  and commit only encrypted EYAML blocks to `nest/private`.

## Current incident notes

During the June 2026 Talon/Star divergence, Talon had a refreshed local Codex
credential while Star still had a local pool entry carrying `last_status =
exhausted`, `last_error_code = 429`, and `last_error_reason =
usage_limit_reached`. Star recovered only after Joy reauthed Star directly. The
managed slot policy above prevents that class of divergence by making
profile-local Codex entries temporary migration sources and keeping steady-state
selection in a shared root fallback plus private labelled slot store.
