# Hermes Agent 0.16.0 upgrade preparation

## Phase 0/1 gate: forked 0.15.2 baseline

The live managed Hermes install on owl is currently at upstream tag `v2026.5.29.2`,
commit `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`, with installed package
version `0.15.2`. Joy's GitLab fork is anonymously readable at:

```text
https://gitlab.joyfullee.me/nest/forks/hermes-agent.git
```

The fork carries the same annotated `v2026.5.29.2` tag and the same peeled commit
`77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`, so switching the managed remote to
that fork while keeping `nest::app::hermes::git_ref: 'v2026.5.29.2'` is a
0.15.2-equivalent source cutover, not a runtime version upgrade.

This branch changes the class default `git_url` to the fork URL and adds a
managed `set_hermes_source_remote` normalization exec before the Hermes source
`vcsrepo`. That mirrors the existing broker remote-normalization pattern and
lets Puppet migrate the existing `/opt/hermes-agent/src` checkout from upstream
GitHub to the fork before `puppetlabs-vcsrepo` checks the desired source.

## Puppet-managed local patch inventory

The Hermes install still applies a substantial Puppet-managed patch stack from
`files/app/hermes/*.patch`. For the 0.15.2 fork cutover, keep these in place and
prove the forked checkout applies them cleanly. For the 0.16.0 rebase, reconcile
them into the fork as first-class commits or consciously drop them if upstream
now covers the behavior.

### Hermes core patches to reconcile onto the fork

These patch live Hermes Agent source under `/opt/hermes-agent/src` and therefore
must be rebased or retired before the 0.16.0 runtime upgrade:

- Dashboard/public access and UI rendering: `dashboard-insecure-websockets.patch`,
  `dashboard-chat-truecolor-env.patch`, `dashboard-rich-art-spans.patch`,
  `dashboard-skin-branding.patch`.
- CLI/banner/profile skin behavior: `banner-hero-renderable.patch`,
  `banner-logo-suppression.patch`,
  `cli-discover-custom-toolsets-before-validation.patch`.
- Telegram/gateway UX and agent-request callback handling:
  `telegram-tool-preview-length.patch`, `telegram-agent-request-callbacks.patch`,
  `telegram-agent-request-callback-preserve-text.patch`,
  `telegram-agent-request-unstuck-command.patch`,
  `hermes-telegram-voice-summary.patch`.
- Kanban/agent-request substrate and dashboard behavior:
  `kanban-agent-request-notification-hook.patch`,
  `kanban-agent-request-dispatch-notification-hook.patch`,
  `kanban-agent-request-failure-notification-hook.patch`,
  `kanban-agent-request-failure-notification-posttxn.patch`,
  `kanban-agent-request-unblocked-summary.patch`,
  `kanban-agent-request-completion-sync.patch`,
  `kanban-agent-request-review-dispatch-gate.patch`,
  `kanban-review-required-block-fallback.patch`,
  `kanban-actionable-attention.patch`,
  `kanban-frontend-actionable-attention.patch`,
  `kanban-review-lane-metadata.patch`,
  `kanban-completion-worktree-cleanup.patch`,
  `kanban-completion-worktree-cleanup-response-json.patch`,
  `kanban-prod-smoke-board-guard.patch`,
  `kanban-prod-smoke-lowlevel-guard.patch`,
  `kanban-auto-resume-structured-blockers.patch`,
  `kanban-auto-resume-systemd-unix-timestamps.patch`,
  `kanban-requeue-interrupted-worker-owner-exit.patch`,
  `kanban-gave-up-running-race-repair.patch`,
  `kanban-dispatcher-profile-scope.patch`,
  `kanban-tools-test-isolate-board-env.patch`.

### Agent-request broker patches

These target `/opt/hermes-agent/agent-request-broker`, not the Hermes Agent
source checkout. They should be reconciled into the broker repository separately,
but they still matter during 0.16.0 testing because Hermes, the custom tool
module, and the broker share the Agent Requests/Kanban UX contract:

- Review/state-machine flow: `agent-request-review-handoff-flow.patch`,
  `agent-request-review-notification-binding.patch`,
  `agent-request-review-question-answer.patch`,
  `agent-request-review-requested-attention.patch`,
  `agent-request-superseded-review-parent.patch`,
  `agent-request-blocking-child-review-guard.patch`,
  `agent-request-blocking-child-wakeup.patch`,
  `agent-request-future-milestone-dependency.patch`.
- Notifications and Telegram UX: `agent-request-child-task-notifications.patch`,
  `agent-request-telegram-delivery-profile-routing.patch`,
  `agent-request-telegram-unstuck.patch`,
  `agent-request-recipient-profile-tts.patch`,
  `agent-request-comment-label.patch`,
  `agent-request-notification-narrow-redaction.patch`,
  `agent-request-watchdog-actionable-reminder.patch`.
- Board/workspace hygiene and cleanup: `agent-request-worktree-cleanup.patch`,
  `agent-request-completed-archive-policy.patch`,
  `agent-request-dev-board-labels.patch`,
  `agent-request-dev-board-override.patch`,
  `agent-request-dev-board-current-db.patch`,
  `agent-request-stale-blocked-parent-reconcile.patch`,
  `agent-request-direct-kanban-fallback-review-code.patch`,
  `agent-request-direct-kanban-fallback-review-test.patch`.

### Removed/cleanup-only patch handling

`reset_hermes_source_for_removed_kanban_diagnostic_patches`,
`reset_hermes_source_for_contextless_agent_request_callbacks`, and the absent
`kanban-cross-board-*` / `kanban-legacy-prose-*` patch files are cleanup guards
for older patch attempts. Keep them through the fork cutover so a stale checkout
is normalized before the active patch stack applies. During the 0.16.0 rebase,
revisit whether these guards can be removed after the fork contains a clean patch
history and no live hosts retain those older diffs.

## 0.16.0 rebase strategy

Upstream tag `v2026.6.5` has `pyproject.toml` version `0.16.0`. Joy's fork does
not yet advertise that tag in the checked probe, so the safe path is:

1. Review and merge this source change, then deploy Puppet code and apply owl
   without changing `git_ref` from `v2026.5.29.2`.
2. After convergence, verify `/opt/hermes-agent/src` has origin
   `https://gitlab.joyfullee.me/nest/forks/hermes-agent.git`, HEAD
   `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`, package version `0.15.2`, and no
   unexpected dirty source state besides Puppet-managed patches.
3. Restart/reload the affected Hermes profile services only with Joy-approved
   timing, then verify Talon, Star, dashboard, native Kanban, and the
   `agent_request_*` request/status path from the live runtime.
4. In the fork, import upstream `v2026.6.5`/0.16.0 and rebase the Hermes core
   patch groups above as normal commits, preferring upstream equivalents where
   0.16.0 already solved the problem. Keep broker patches in the broker repo.
5. Run focused upstream/Puppet checks against the rebased fork: patch application
   should disappear or become no-op because the fork contains the changes;
   package install should succeed from the fork; Hermes doctor/tool availability
   should still expose Talon/Star's expected toolsets; Kanban/Agent Requests
   should pass request, review/proposal, notification, and cleanup smoke tests on
   a dev board before production.
6. Only after the forked 0.16.0 branch passes those gates should Hiera move
   `nest::app::hermes::git_ref` from `v2026.5.29.2` to the approved 0.16.0 fork
   tag/commit, followed by Puppet deploy, owl apply twice, service restart, and
   live verification.

## Rollback

The Phase 0/1 source cutover is reversible by setting `git_url` back to upstream
GitHub while leaving `git_ref: 'v2026.5.29.2'`. The new remote-normalization exec
will migrate the existing checkout's `origin` in either direction before
`vcsrepo` validates it.
