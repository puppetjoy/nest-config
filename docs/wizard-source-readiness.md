# Disabled Wizard source readiness and parent rollout ordering

This prerequisite prepares source only. It does not deploy, restart, apply host
Puppet, enable Wizard, or change Native, Broker or Flight Deck source pins.
The parent owns the accepted final source tuple and installed acceptance.

## Managed configuration and ownership

`nest::app::hermes::instances.<instance>.kanban_wizard` passes through the existing
`nest::app::hermes::config` / `nest::lib::hermes` managed configuration path to
Native's `kanban.wizard`. Missing fields receive exactly these defaults:

```yaml
kanban_wizard:
  enabled: false
  boards: []
  model: {}
  integrations: []
```

The `Nest::Wizard` type bounds boards to at most 100 nonempty strings, types
integration names as strings, and permits only `provider`, `model`, `base_url`
and `api_mode` string routing fields. No credentials belong in this mapping.
Native still validates nonempty boards and model plus registered integrations
when explicitly enabled. No new profile, timer, scheduler or lifecycle owner is
introduced. Native's existing service role uses Talon's profile and credential
scope, regardless of the dispatcher process's profile. Keep the existing dispatch
owner and `kanban_dispatch_in_gateway` policy unchanged; do not enable this on
multiple profile dispatchers. No instance opts in in this source change.
System-owned Python/uv policy is untouched; coordinate the parent's external
runtime retirement prerequisite before any apply.

## Consumer packaging and filesystem contract

The existing init container fetches the complete Flight Deck Git tree at the
source-managed immutable pin. There is no module allowlist: `wizard_chat.py` and
`orchestration.py` from corrective Flight Deck merge
`366df1a36da31a23341dee6e5fe98fe39335e82d` are included by the same checkout path.
Do not copy selected modules into a serving image or import Native there.
Current service pins remain unchanged until the parent's separate promotion.

The kanban hostPath and container mount now both use
`/home/joy/.hermes/kanban`; `HERMES_KANBAN_HOME` points there. Native board-local
Wizard JSONL receipts retain their canonical absolute paths and device/inode
identity. Worker logs follow this same root. Existing participant, artifact and
profile mounts remain intact. Application source stays read-only. The board
mount remains writable solely to preserve SQLite WAL/shm coordination; this
is not API mutation authority. The corrective consumer uses query-only reads
and rejects changed, foreign or unsafe log receipts.

No serving UID policy or production permissions are changed here. Before parent
rollout, verify the actual serving UID can traverse the existing board directory
and read producer-private sinks. Compare the same sink's device/inode in producer
and serving container; do not chmod/chown state, remap receipt paths, regenerate
logs, or weaken the identity checks to make a failing acceptance pass.

## Parent apply and opt-in sequence (not executed here)

1. Freeze and record a coherent, merged, exact-CI-accepted Nest/Native/Broker/
   Flight Deck tuple. Native contract source is
   `94125885695e316b4726d4063d0d6907210f1bba`, merge
   `e32396011f6416672e36f884d64b2388303f2d1d`. Corrective consumer contract is the
   Flight Deck merge above. These are compatibility references, not permission to
   advance pins. Do not deploy an unmerged parent Broker candidate.
2. Keep `enabled: false`. Merge the parent's chosen immutable source pins through
   the normal source workflow. From that accepted Nest project root install
   modules with `bolt module install`; render DEV and production using existing
   `nest::eyrie::ai::deploy_flight_deck_dev` and
   `nest::eyrie::ai::deploy_flight_deck_prod` plans with nonempty
   `render_to=/modules/nest/build/<private-render>.yaml`. Never use
   `deploy=false` as render evidence. Rendered Secrets stay private.
3. For authorized host convergence, inspect existing Puppet plans, run
   `bolt inventory show owl --detail --format json` and
   `bolt command run 'id -un && hostname -f' --targets owl --stream`, then use
   `bolt plan run nest::puppet::deploy` and
   `bolt plan run nest::puppet::run targets=owl` from the accepted project root.
   Coordinate ordinary managed restarts with the parent; this prerequisite
   neither runs those commands nor authorizes runtime retirement.
4. Deploy the accepted consumer to DEV through
   `bolt plan run nest::eyrie::ai::deploy_flight_deck_dev source_revision=<DEV-pin>`.
   Verify actual serving Git HEAD and revision receipt, both packaged modules,
   canonical board root, UID access, device/inode parity, query-only API and
   unchanged worker/profile/participant/artifact views before proceeding.
5. Opt in only the existing dispatcher owner's per-instance mapping, first with
   `boards: [agent-requests-dev]`, an explicitly accepted Talon model route and
   exact registered integration names. Apply through the same managed host path.
   No credentials, separate Wizard profile or scheduler. Verify genuine
   model-backed event-to-action, original outcomes and lazy execution logs in
   the existing Firefox chat; source tests are not installed acceptance.
6. After DEV acceptance, merge the same accepted consumer tuple into production
   service data, use `deploy_flight_deck_prod source_revision=<production-pin>`,
   repeat provenance and read-only checks, and only then explicitly add the
   production board to the owner's opt-in mapping through managed Puppet.
   Parent retains remaining capability, browser and outcome closure gates.

## Rollback

First set the existing owner's `kanban_wizard.enabled` to `false` through managed
source and ordinary Puppet convergence. This disables the Native case dispatcher
without disabling ordinary Kanban dispatch. Observe bounded active execution
settlement; preserve ambiguous external-effect receipts and never replay them.
Do not delete cases, ledgers, execution sinks, comments, logs or approvals.

Then, if needed, restore the previously accepted consumer pin using the same
DEV-before-production service-data and deploy plans. Keep the canonical board
mount while retained Wizard receipts exist. Only roll Native/Broker source back
after confirming retained-schema compatibility and quiescence; do not down-migrate
or recreate board databases. Restore an old tuple only with the parent's explicit
acceptance, not by overwriting runtime state. Disabling the Wizard is reversible;
retained cases and receipts remain available for later supported recovery.
