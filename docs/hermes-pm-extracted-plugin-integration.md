# Managed Hermes PM and extracted-plugin integration

Source-only prerequisite for Agent Request ^2205 / task t_fc1cf4cf. This change is not a live upgrade and does not release rollout ^2206. The configuration MR must remain unmerged until that coordinated rollout.

## Source identities

- Deployed Hermes comparison: `04fe62345b00986e6a1f4d4776296f7c1e82e1ce`, retained by the parent as `safety/t_fc1cf4cf-nest-04fe62345b`.
- Exact immutable core tested here: `085f562af53a6fedadac3681e2c498fc71316132`. The acceptance harness exports this commit, never the parent's conflicted working tree.
- Broker package tested here: `59f6ed9808c98cb4a74b096140b26edc894e0ebb`, exported from the read-only broker repository.
- Honcho: `plastic-labs/honcho` at `e2d2aba182862deeb846e5cd4a30a41bce0ed82a`, subdirectory `hermes-plugin-honcho`.
- Camofox: `NousResearch/hermes-official-plugins` at `190593f4ce4c481a80ed27448535c867c5c6e27f`, subdirectory `camofox`.
- Copilot: `NousResearch/hermes-labs-plugins` at `346cfe972f72b6a966e84c1004cf8742554b193d`, subdirectory `github-copilot`.

Read-only GitLab fork discovery found `nest/forks/honcho` and `nest/forks/hermes-agent`, not a registered plugin-specific fork. The Honcho server fork does not contain the required plugin commit: its Git upload-pack rejected that exact object. No fork ref was created or moved. The plugin therefore uses the prescribed immutable upstream input plus a Nest patch.

The delivered `staged-plugins/sources.json` records the source URLs, exact commits, subdirectories, patch SHA-256 values and every staged file's SHA-256. The archive exports actual patched plugin trees, not reconstructed API responses or vendor modules restored to Hermes core.

## Activation and ownership

`nest::app::hermes::pm_enabled` defaults to `false`. No host Hiera activation is included. Enabling PM requires full immutable core `git_commit` and broker `broker_git_ref` pins; a catalog with incomplete pins fails before applying any resources.

Legacy mode retains Python 3.13, the existing virtualenv and its dependency installers. The new stable `bin/hermes-python` wrapper delegates to that same interpreter in legacy mode. CLI, profile, gateway, dashboard, broker, Google helpers, Star's order runner, release inspection, and backup/restore entry points no longer need to guess the PM generation's location. Backup and restore use the published `/usr/local/bin/hermes` command.

PM mode provisions a Python 3.14 bootstrap, then asks the exact target's public `pm.sync_venv` API for the `all` extra and the external dependency union. It does not invoke pip or uv. The broker's existing buildable source directory is a PM workspace member, exposed through the ordinary plugin discovery path as a no-tool dependency plugin. This is important: a direct-URL requirement in a synthetic wrapper was experimentally rejected by PM's declaration filtering. The final implementation uses the actual broker package member instead. Its profile enablement preserves it in future ordinary PM plugin transactions.

PM sync runs as the Nest user. Selection state belongs to `/home/joy/.hermes/installs`, shared by that root's named profiles; the managed writable tool store is `${install_dir}/tools`. It must not select dependencies under a separate `/opt` data home and then expect normal user profiles to find them. The Python adapter uses upstream `runtime_command` and `hermes_bootstrap`, clears inherited Python environment selection, activates the committed generation and acquires upstream leases. It never persists a generation path.

Profile-local links point to immutable staged plugin assets. Honcho and Copilot use their upstream specialized loaders. Browser-enabled profiles additionally enable `camofox` and add its upstream `camofox` toolset without renaming any `browser_*` tool. Existing operational plugins remain in place. No observer, updater timer, alternate registry, or new provenance service is introduced.

## Behavioral retention

Honcho's patch retains content-identity invalidation, completed delayed-recall discard for acknowledgement turns, compact dialectic budgets and the no-concise-result sentinel, native evaluation probes and identity-relation audit. Absolute self-imports in the carried CLI additions became relative imports. The old required session/evaluation/audit tests are retained with external import targets; additional deployed identity, client isolation, turn-author and context tests are carried too. A same-size, same-mtime workspace repoint is explicitly tested. The pinned core's narrower acknowledgement classifier is extended at the plugin boundary for the deployed acknowledgement forms; the parent remains responsible for its shared core classifier/current-turn changes.

Camofox's patch retains configured/default desktop dimensions, creates a blank tab before explicit navigation, requests `fullPage=false`, and returns image dimensions, viewport metrics and mismatch information in screenshot metadata. Its upstream REST-server tests were adapted to assert the new blank-tab/navigation sequence rather than deleted. New viewport and screenshot regressions exercise the real implementation.

Copilot requires no Nest source delta on the pinned external plugin, so its patch file is deliberately empty. This was checked against the deployed provider profiles, `hermes_cli/copilot_auth.py` and the ACP client rather than inferred from commit titles. The external implementation moves authentication/client logic behind the target's generic provider seams. Unlike the old resolver's `gh auth token` fallback, the upstream plugin deliberately obtains credentials through Hermes only. Its tests prohibit reading CLI token stores or invoking the CLI for credentials. Real profile discovery retains `copilot`, `github-copilot` and `copilot-acp` identities; a scoped credential test verifies employer-token precedence and refusal to borrow ambient personal GitHub tokens when the scope is empty.

Quill's existing `copilot/gpt-6.1-terra` primary, Copilot helper/delegation routes, non-inherited credentials and Hawk SSH backend are unchanged. No host data, personal provider assignment or Beryl local-only model policy is changed.

## Reproduce the isolated acceptance

From this configuration checkout, with Python 3.14 available:

    python3.14 scripts/test-hermes-managed-integration.py \
      --core-repo /path/to/read-only/hermes-agent \
      --broker-repo /path/to/read-only/hermes-agent-request-broker \
      --broker-sha 59f6ed9808c98cb4a74b096140b26edc894e0ebb \
      --work /path/to/a/new/empty/local-workspace

The harness refuses an existing destination, strips ambient profile/provider context, exports immutable source snapshots, stages and verifies the actual patches, performs the production PM sync, then adds a test-only pytest member through PM. It runs every group through the real PM-shaped launcher. JUnit and `results.json` retain failure, error and skip counts; any skipped test fails this acceptance harness. No live profile or service is used.

The complete fresh run passed:

| Group | Passed | Failed | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Honcho | 151 | 0 | 0 | 0 |
| Camofox | 94 | 0 | 0 | 0 |
| Copilot | 144 | 0 | 0 | 0 |
| Runtime and real external discovery | 6 | 0 | 0 | 0 |

This is 395 Python tests, in addition to focused Puppet/Quill/model-policy/backup-plan tests and `pdk validate`. These are managed-source acceptance results, not the parent's full-suite result or production verification. The deliverable includes the fresh run's JUnit files, logs and machine-readable results. Earlier failed probes are not substituted for final receipts.

## Promotion and install order — rollout ^2206 only

1. Parent independently verifies the archive hash and staged-file hashes, runs the exported tests against the exact target, finishes core conflicts and its complete non-pass ledger, and produces its unmerged exact-head Hermes MR. Do not use this source-only child as approval of the core port.
2. Verify both final MR heads and CI, inventory-backed Bolt transport, the exact currently deployed core/broker/config revisions and a complete native Hermes-root backup. Preserve the old source checkout and Python 3.13 runtime as rollback material. Keep backup staging local; `/nest/backup` is the final destination.
3. Freeze automatic Puppet follow-through for the coordinated interval and drain/stop affected gateways and dashboards using the established managed operational path. Do not replace files under processes that can lazily import a mixture of releases.
4. Rollout owns all merges. Promote the reviewed core and this configuration together with an activation change setting `pm_enabled: true`, the final tested immutable core pin and the chosen tested immutable broker pin. Do not merge the port to a floating production ref and let an ordinary legacy Puppet run consume it first.
5. Apply through the existing inventory-backed Bolt/Puppet path. The catalog verifies the source pin, realizes exact external sources plus patches, provisions the PM-owned dependency union as the Nest user, switches stable wrappers/services, installs profile links and manages the upstream plugin/toolset selection. Frontend builds depend on the completed PM runtime before using the Python build-state helper.
6. Before accepting traffic, verify PM currency and package imports through the stable wrapper, core/broker/source identities, real external provider and tool discovery for each actual profile, the required Honcho boundaries and browser behavior, Quill employer/helper/delegation/Hawk behavior, Beryl policy, backup entry points and rebuilt frontends. Start only the intended services and inspect actual runtime readiness. This child has not performed those live checks.

## Rollback order

1. Stop/drain the same services and preserve the failing PM receipt and runtime identities without collecting credentials.
2. Restore the previously recorded configuration/source revision and immutable pre-upgrade core/broker pins through the same managed Bolt/Puppet path, with `pm_enabled: false`. Keep the preserved Python 3.13 runtime available. The stable Python/CLI/service wrappers return to legacy mode; no raw pip repair of the PM store is part of rollback.
3. Restore the full Hermes-root backup only if data compatibility requires it, using the existing native import plan; do not rewrite OAuth tokens from Puppet. Retained external asset links are not blanket-deleted: the managed enabled/toolset additions are withdrawn, the old bundled Honcho provider wins, and the upstream Camofox/Copilot plugins explicitly remain inert on a core that still bundles them. Inspect those guards and effective discovery before restarting; remove only rollout-owned links if a verified rollback requires it, not unrelated user plugins.
4. Verify the old source/interpreter, profile discovery, model isolation, backup/import and service readiness, then reopen traffic and automatic Puppet. Do not garbage-collect either runtime or the rollback generation until rollout acceptance is complete.
