# Hermes Puppet refactor audit

Task: `t_cb5e0206` / Agent Request `ar-20260608-172622-1bbc94`

Scope reviewed in this worktree:

- `Puppetfile`
- `metadata.json`
- `manifests/app/hermes.pp`
- `manifests/app/hermes/install.pp`
- `manifests/app/hermes/config.pp`
- `manifests/app/hermes/service.pp`
- `manifests/lib/hermes.pp`
- `files/app/hermes/*`
- `templates/app/hermes/*`

## Current resource inventory

Naive manifest inventory after the review-change refactor:

- `nest::app::hermes::install`: 2 `vcsrepo`, 12 `exec`, 11 `file`, 3 `nest::lib::package`, 1 `nest::lib::package_use`, 1 `python::pyvenv`, 2 `python::pip`
- `nest::app::hermes::config`: 1 `exec`, 3 `file`
- `nest::app::hermes::service`: 7 `file`, 2 `systemd::manage_unit`, 1 `systemd::daemon_reload`, 1 `loginctl_user`
- `nest::lib::hermes`: 3 profile-scoped `exec`, 12 `file`, 3 direct `nest::lib::package_use`, 4 profile-scoped `systemd::user_service`

The remaining `exec` resources now line up with source/build/config actions that still have Hermes-specific state checks: source checkout remote normalization, source-revision-tracked install/reinstall, TUI/web/npm builds, managed config merge/apply, Codex auth sharing, and refresh-only service restarts.

## Cleanup/refactor classification

Safe/refactor cleanup included in this branch:

- Replaced the hand-rendered `managed-config.yaml` heredoc in `nest::lib::hermes` with a Puppet hash rendered through `stdlib::to_yaml`. This preserves the same keys while making nested YAML structure reviewable as Puppet data instead of string indentation.
- Moved embedded helper script content out of manifests and into EPP templates:
  - `templates/app/hermes/manage-hermes-config.py.epp`
  - `templates/app/hermes/dashboard.sh.epp`
  - `templates/app/hermes/profile-wrapper.py.epp`
  - `templates/app/hermes/agent-request-command.sh.epp`
- Collapsed three duplicate agent-request CLI wrapper loops into one wrapper list using the shared EPP template. The managed command names, environment exports, target broker scripts, owner/group/mode, and ordering remain the same.
- Added Vox Pupuli `puppet-python` to the control repo and replaced direct virtualenv creation plus simple published venv dependency installs with `python::pyvenv` and `python::pip` resources.
- Leveraged Vox Pupuli `puppet-systemd` for user unit file rendering, user daemon reload, linger, and enable/start state via `systemd::manage_unit`, `systemd::daemon_reload`, `loginctl_user`, and `systemd::user_service`.
- Preserved the existing install/config/service + lib organization that Joy called understandable.

Cleanup retired after Joy's review steering and live absence evidence:

- Retired top-level/default-profile cleanup for obsolete `~/.hermes` paths and old `~/.hermes/agent-requests`; checked 67 legacy paths on owl and found `existing_count 0`.
- Retired legacy agent-request watcher command and unit absence resources; `systemctl --user list-unit-files 'hermes-agent-request*'` returned no units on owl.
- Retired one-time patch/build artifact cleanup resources for old kanban patch files, rejected patch artifacts, bytecode, and egg-info directories. The scoped host is owl and the audited legacy path set was already absent.
- Retired absence resources for old singleton gateway/dashboard units and drop-in directories after the same path audit found none present.

Deferred as behavior-changing or broader follow-up:

- Replacing source-revision-tracked Hermes and broker install/reinstall `exec` resources with plain `python::pip` would lose the explicit git revision marker and force-reinstall behavior, so those stayed as guarded lifecycle execs.
- Replacing refresh-only gateway restart logic with a generic `systemd::user_service` notification would lose the existing `hermes-systemd-user-refresh` timeout behavior; restart execs stayed, but only as refresh hooks.
- Live deploy/apply/restart/manual orphan cleanup remains deferred for review acceptance.

## Validation performed

- Live read-only cleanup evidence on owl: checked 67 retired legacy paths, found `existing_count 0`; `systemctl --user list-unit-files --no-legend 'hermes-agent-request*'` returned no units.
- `git diff --check`
- `pdk validate --parallel=false --format text`

Both source validators passed in this worktree after the review-change edits. A non-required `pdk bundle exec r10k puppetfile check` probe was attempted but blocked by missing local bundle gems in the host environment, not by Puppetfile syntax.

## Deploy/apply/restart boundary

No Puppet deploy, Puppet agent run, service restart, gateway restart, dashboard restart, or live cleanup was performed. Those remain deferred until review acceptance.
