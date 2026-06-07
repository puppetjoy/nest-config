# Hermes Puppet patch migration audit

Task: `t_722214b6`

This audit covers the Hermes-related `patch` resources in
`manifests/app/hermes/install.pp` and the patch files under
`files/app/hermes/`. The Nest config checkout is the isolated worktree at
`/home/joy/projects/.worktrees/nest-config/t_722214b6`; the Hermes Agent fork
was inspected in the task worktree
`/home/joy/projects/.worktrees/hermes-agent/t_722214b6`, detached at
`7050182dd5c549f88bd9f9c5b8ba244ee9019db7` (`origin/hermes/0.16.0-nest`, tag
`nest/v0.16.0`) before follow-through. The accepted follow-through migrated the
remaining source dependency patch to fork commit
`4a8829c9fd05d5f02ec21a76868f93812d65eab2` and fast-forwarded
`origin/hermes/0.16.0-nest` plus `origin/joy/nest-0.16.0-patch-stack` to that
commit.

## Summary

- At audit time, `install.pp` defined 35 Hermes Agent source patch execs that
  applied to `${source_dir}`.
- A later cleanup task retired the remaining redundant Hermes Agent source patch
  resources after the fork ref `nest/v0.16.0` contained the behavior; the patch
  payload files for those `${source_dir}` patches were removed from
  `files/app/hermes/`.
- `install.pp` still defines agent-request-broker patch execs that apply to
  `${broker_source_dir}`. Those are broker maintenance, not candidates for the
  Hermes Agent fork.
- 34 of the 35 Hermes Agent source patch execs were already covered by the
  Hermes Agent fork ref that Puppet pinned on owl at audit time.
- The one remaining durable Hermes Agent source change still only represented
  as a Puppet patch at audit time was
  `dashboard-python-multipart-dependency.patch`; it is now covered by fork
  commit `4a8829c9f`.
- No deploy or Puppet apply was performed during this audit or follow-through.

## Evidence used

- Puppet source:
  - `manifests/app/hermes/install.pp`
  - `files/app/hermes/*.patch`
  - `data/host/owl.yaml`, which pins `nest::app::hermes::git_ref` to
    `hermes/0.16.0-nest` and now pins `nest::app::hermes::git_commit` to
    `4a8829c9fd05d5f02ec21a76868f93812d65eab2`
- Hermes Agent fork:
  - `origin/hermes/0.16.0-nest` and `origin/joy/nest-0.16.0-patch-stack` both
    resolved to `7050182dd` in the task worktree at audit time and now resolve
    to `4a8829c9f`
  - `git log --oneline --reverse upstream/v0.16.0..HEAD` shows the `nest: apply
    ...` patch migration commits listed below
  - targeted `git grep` checks confirmed current-file coverage for patches that
    no longer reverse-apply byte-for-byte because later fork commits evolved the
    same code

## Hermes Agent source patch inventory

Classification legend:

- `covered in fork`: the durable source change is already in the pinned Hermes
  Agent fork ref.
- `covered by later fork fix`: the literal patch is superseded by a later fork
  commit, but the intent is present in current source.
- `migrate to fork`: the patch is still only in Puppet and should be committed
  to the Hermes Agent fork before the Puppet patch is retired.

| Patch file | Puppet exec | Classification | Fork evidence |
| --- | --- | --- | --- |
| `dashboard-insecure-websockets.patch` | `patch_hermes_dashboard_insecure_websockets` | covered in fork | `c00322fd5 nest: apply dashboard-insecure-websockets`; current `hermes_cli/web_server.py` contains `app.state.allow_public = allow_public` |
| `dashboard-python-multipart-dependency.patch` | `patch_hermes_dashboard_python_multipart_dependency` | migrated to fork; Puppet patch cleanup prepared | Fork commit `4a8829c9f deps: ship python-multipart with dashboard` adds `python-multipart==0.0.32` to `pyproject.toml` and updates `uv.lock`; the Nest config cleanup removes this Puppet patch wiring while keeping the install smoke for `m.version('python-multipart')` |
| `telegram-tool-preview-length.patch` | `patch_hermes_telegram_tool_preview_length` | covered in fork | `326ff441d nest: apply telegram-tool-preview-length` |
| `telegram-agent-request-callbacks.patch` | `patch_hermes_telegram_agent_request_callbacks` | covered in fork | `95d1780af nest: apply telegram-agent-request-callbacks`; callback tests exist in `tests/gateway/test_telegram_agent_request_callbacks.py` |
| `telegram-agent-request-callback-preserve-text.patch` | `patch_hermes_telegram_agent_request_callback_preserve_text` | covered in fork | `6da2e2ed4 nest: apply telegram-agent-request-callback-preserve-text`; current Telegram adapter preserves `original_text` |
| `telegram-agent-request-delivery-profile.patch` | `patch_hermes_telegram_agent_request_delivery_profile` | covered by later fork fix | Superseded by `9f558fb22 telegram: pass Hermes profile for agent-request callbacks` and `233b619d3 telegram: derive agent-request profile from active CLI context`; current adapter has `_agent_request_delivery_profile()` |
| `telegram-agent-request-unstuck-command.patch` | `patch_hermes_telegram_agent_request_unstuck_command` | covered in fork | `c21e327ff nest: apply telegram-agent-request-unstuck-command`; current adapter imports `handle_telegram_unstuck` |
| `banner-hero-renderable.patch` | `patch_hermes_banner_hero_renderable` | covered in fork | `57b03807e nest: apply banner-hero-renderable`; current `hermes_cli/banner.py` has `_banner_hero_renderable` |
| `banner-logo-suppression.patch` | `patch_hermes_banner_logo_suppression` | covered in fork | `7cdb6376d nest: apply banner-logo-suppression`; current branding code supports `NO_BANNER_LOGO` |
| `cli-discover-custom-toolsets-before-validation.patch` | `patch_hermes_cli_custom_toolset_validation` | covered in fork | `d4e9dca10 nest: apply cli-discover-custom-toolsets-before-validation` |
| `kanban-tools-test-isolate-board-env.patch` | `patch_hermes_kanban_tools_test_isolate_board_env` | covered in fork | `22cd93e16 nest: apply kanban-tools-test-isolate-board-env`; current tests include worker fixture isolation comment |
| `kanban-agent-request-notification-hook.patch` | `patch_hermes_kanban_agent_request_notification_hook` | covered in fork | `77216e80f nest: apply kanban-agent-request-notification-hook`; current `tools/kanban_tools.py` has `_notify_agent_request_event` |
| `kanban-agent-request-unblocked-summary.patch` | `patch_hermes_kanban_agent_request_unblocked_summary` | covered by later fork fix | Current `tools/kanban_tools.py` emits `Approved/unblocked/resumed; task is eligible to continue.`; literal patch lacks a git header and is already incorporated in current code |
| `kanban-agent-request-dispatch-notification-hook.patch` | `patch_hermes_kanban_agent_request_dispatch_notification_hook` | covered in fork | `597a32eb1 nest: apply kanban-agent-request-dispatch-notification-hook`; current `hermes_cli/kanban_db.py` has `_notify_agent_request_dispatch_event` |
| `kanban-agent-request-failure-notification-hook.patch` | `patch_hermes_kanban_agent_request_failure_notification_hook` | covered in fork | `2ed22c1a6 nest: apply kanban-agent-request-failure-notification-hook` |
| `kanban-agent-request-failure-notification-posttxn.patch` | `patch_hermes_kanban_agent_request_failure_notification_posttxn` | covered in fork | `80eb87ab8 nest: apply kanban-agent-request-failure-notification-posttxn`; current code has `notify_after_failure_txn` |
| `kanban-gave-up-running-race-repair.patch` | `patch_hermes_kanban_gave_up_running_race_repair` | covered in fork | `ad1568c70 nest: apply kanban-gave-up-running-race-repair`; current code has `repair_gave_up_running_divergence` |
| `kanban-dispatcher-profile-scope.patch` | `patch_hermes_kanban_dispatcher_profile_scope` | covered in fork | `36158c156 nest: apply kanban-dispatcher-profile-scope`; current gateway passes `dispatcher_profile=dispatcher_profile` |
| `kanban-actionable-attention.patch` | `patch_hermes_kanban_actionable_attention` | covered in fork | `3047b3ebe nest: apply kanban-actionable-attention`; current plugin API has `_attention_summary_for_task` |
| `kanban-frontend-actionable-attention.patch` | `patch_hermes_kanban_frontend_actionable_attention` | covered in fork | `e5dfdb1db nest: apply kanban-frontend-actionable-attention` |
| `kanban-review-lane-metadata.patch` | `patch_hermes_kanban_review_lane_metadata` | covered in fork | `5623fb20b nest: apply kanban-review-lane-metadata`; current plugin API has `BOARD_COLUMN_METADATA` |
| `kanban-agent-request-review-dispatch-gate.patch` | `patch_hermes_kanban_agent_request_review_dispatch_gate` | covered in fork | `fb7d14dd8 nest: apply kanban-agent-request-review-dispatch-gate`; current code notes review handoffs wait for Joy/operator approval |
| `kanban-completion-worktree-cleanup.patch` | `patch_hermes_kanban_completion_worktree_cleanup` | covered in fork | `eff030be9 nest: apply kanban-completion-worktree-cleanup`; current completion path calls broker cleanup hooks |
| `kanban-completion-worktree-cleanup-response-json.patch` | `patch_hermes_kanban_completion_worktree_cleanup_response_json` | covered by later fork fix | Current `tools/kanban_tools.py` parses `_ok(...)` with `json.loads` before adding cleanup metadata |
| `kanban-agent-request-completion-sync.patch` | `patch_hermes_kanban_agent_request_completion_sync` | covered in fork | `6eb935937 nest: apply kanban-agent-request-completion-sync`; current completion path calls `agent_request_task_completed` |
| `kanban-review-required-block-fallback.patch` | `patch_hermes_kanban_review_required_block_fallback` | covered in fork | `93884d44e nest: apply kanban-review-required-block-fallback`; current code uses `kanban_block_review_required` source metadata |
| `kanban-prod-smoke-board-guard.patch` | `patch_hermes_kanban_prod_smoke_board_guard` | covered in fork | `462681d4a nest: apply kanban-prod-smoke-board-guard`; current tools have `_prod_agent_requests_smoke_guard` |
| `kanban-prod-smoke-lowlevel-guard.patch` | `patch_hermes_kanban_prod_smoke_lowlevel_guard` | covered in fork | `f4c887ec0 nest: apply kanban-prod-smoke-lowlevel-guard`; current DB code has `_reject_prod_agent_requests_smoke_task` |
| `kanban-auto-resume-structured-blockers.patch` | `patch_hermes_kanban_auto_resume_structured_blockers` | covered in fork | `33b924fca nest: apply kanban-auto-resume-structured-blockers`; current DB code has `auto_resume_satisfied_blockers` |
| `kanban-auto-resume-systemd-unix-timestamps.patch` | `patch_hermes_kanban_auto_resume_systemd_unix_timestamps` | covered in fork | `168ab8844 nest: apply kanban-auto-resume-systemd-unix-timestamps`; current code invokes `systemctl` with `--timestamp=unix` |
| `kanban-requeue-interrupted-worker-owner-exit.patch` | `patch_hermes_kanban_requeue_interrupted_worker_owner_exit` | covered in fork | `e9cf68505 nest: apply kanban-requeue-interrupted-worker-owner-exit`; current code has `_claim_owner_alive` |
| `hermes-telegram-voice-summary.patch` | `patch_hermes_telegram_voice_summary` | covered in fork | `ee5f09817 nest: apply hermes-telegram-voice-summary`; current gateway has `_summarize_text_for_voice_reply` |
| `dashboard-rich-art-spans.patch` | `patch_hermes_dashboard_rich_art_spans` | covered in fork | `b2cb3267a nest: apply dashboard-rich-art-spans`; current TUI banner parser has `RICH_OPEN_RE` |
| `dashboard-chat-truecolor-env.patch` | `patch_hermes_dashboard_chat_truecolor_env` | covered in fork | `b523ce516 nest: apply dashboard-chat-truecolor-env` |
| `dashboard-skin-branding.patch` | `patch_hermes_dashboard_skin_branding` | covered in fork | `64d712ffc nest: apply dashboard-skin-branding`; current TUI theme exposes profile skin branding |

## Broker patch inventory

These patch execs target `${broker_source_dir}`, not `${source_dir}`. They should not be
migrated into the Hermes Agent fork. If Joy wants the Puppet patch files retired,
that should be handled as a separate broker cleanup once the deployed broker ref is
known-good and any ordering/array cleanups in `install.pp` are reviewed.

| Patch file | Puppet execs | Classification |
| --- | --- | --- |
| `agent-request-review-handoff-flow.patch` | `patch_hermes_agent_request_review_handoff_flow`, `patch_hermes_agent_request_worktree_cleanup`, `patch_hermes_agent_request_telegram_unstuck`, `patch_hermes_agent_request_telegram_voice_notifications`, `patch_hermes_agent_request_blocking_child_wakeup` | broker-only; not a Hermes Agent fork migration |
| `agent-request-recipient-profile-tts.patch` | `patch_hermes_agent_request_recipient_profile_tts` | broker-only; not a Hermes Agent fork migration |
| `agent-request-comment-label.patch` | `patch_hermes_agent_request_comment_label` | broker-only; not a Hermes Agent fork migration |
| `agent-request-review-question-answer.patch` | `patch_hermes_agent_request_review_question_answer` | broker-only; not a Hermes Agent fork migration |
| `agent-request-dev-board-labels.patch` | `patch_hermes_agent_request_dev_board_labels` | broker-only; not a Hermes Agent fork migration |
| `agent-request-blocking-child-review-guard.patch` | `patch_hermes_agent_request_blocking_child_review_guard` | broker-only; not a Hermes Agent fork migration |
| `agent-request-superseded-review-parent.patch` | `patch_hermes_agent_request_superseded_review_parent` | broker-only; not a Hermes Agent fork migration |
| `agent-request-stale-blocked-parent-reconcile.patch` | `patch_hermes_agent_request_stale_blocked_parent_reconcile` | broker-only; not a Hermes Agent fork migration |
| `agent-request-dev-board-override.patch` | `patch_hermes_agent_request_dev_board_override` | broker-only; not a Hermes Agent fork migration |
| `agent-request-dev-board-current-db.patch` | `patch_hermes_agent_request_dev_board_current_db` | broker-only; not a Hermes Agent fork migration |
| `agent-request-notification-narrow-redaction.patch` | `patch_hermes_agent_request_notification_narrow_redaction` | broker-only; not a Hermes Agent fork migration |
| `agent-request-child-task-notifications.patch` | `patch_hermes_agent_request_child_task_notifications` | broker-only; not a Hermes Agent fork migration |
| `agent-request-review-requested-attention.patch` | `patch_hermes_agent_request_review_requested_attention` | broker-only; not a Hermes Agent fork migration |
| `agent-request-future-milestone-dependency.patch` | `patch_hermes_agent_request_future_milestone_dependency` | broker-only; not a Hermes Agent fork migration |
| `agent-request-direct-kanban-fallback-review-code.patch` | `patch_hermes_agent_request_direct_kanban_fallback_review` | broker-only; not a Hermes Agent fork migration |
| `agent-request-direct-kanban-fallback-review-test.patch` | `patch_hermes_agent_request_direct_kanban_fallback_review_test` | broker-only; not a Hermes Agent fork migration |
| `agent-request-watchdog-actionable-reminder.patch` | `patch_hermes_agent_request_watchdog_actionable_reminder` | broker-only; not a Hermes Agent fork migration |
| `agent-request-review-notification-binding.patch` | `patch_hermes_agent_request_review_notification_binding` | broker-only; not a Hermes Agent fork migration; note this exec exists but is not included in `$broker_patch_execs` |
| `agent-request-completed-archive-policy.patch` | `patch_hermes_agent_request_completed_archive_policy` | broker-only; not a Hermes Agent fork migration |
| `agent-request-telegram-delivery-profile-routing.patch` | `patch_hermes_agent_request_telegram_delivery_profile_routing` | broker-only; not a Hermes Agent fork migration |

## Recommended migration plan

1. In the Hermes Agent fork, create a review branch from
   `origin/hermes/0.16.0-nest` and commit `dashboard-python-multipart-dependency.patch`
   as a normal source change to `pyproject.toml`.
2. Run a focused Hermes Agent validation:
   - `python -m pytest tests/plugins/test_kanban_dashboard_plugin.py`
   - a dependency/install smoke that verifies `import importlib.metadata as m;
     m.version('python-multipart')` after installing the fork
   - a local unauthenticated dashboard plugin API probe should continue to return
     `401`, not the old missing-route `404`, after deploy approval
3. After Joy approves that fork commit and the fork ref/pin moves to a commit that
   includes it, update Puppet source in a separate review-gated Nest config change
   to remove redundant `${source_dir}` Hermes Agent patch payloads and their
   `file`/`exec` wiring from `install.pp`, while keeping the `python-multipart`
   install smoke in `install_hermes_agent` so the managed venv still proves the
   dependency is installed.
4. Treat the broker patch cleanup as a separate task. The broker patches target a
   different repository and should be retired by comparing Puppet patches against
   `/home/joy/projects/nest/hermes-agent-request-broker` and its deployed ref, not
   by migrating them into the Hermes Agent fork.

## Notes

- Several patches no longer reverse-apply exactly against `7050182dd` because the
  fork has subsequent commits that refactored or extended the same code. Those
  are marked as covered by fork source evidence rather than byte-for-byte patch
  reversibility.
- Some short Puppet patch files do not have `diff --git` headers, so `git apply`
  reports them as corrupt even when their target hunks are visibly present in the
  current fork source. They were verified with targeted source greps instead.
