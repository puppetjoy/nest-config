# Telegram transport-receipt managed source release

## Scope and selected composition

This is source preparation for ^2380, the later configuration successor of
completed ^2375. Original ^2341 retains rollout and conversation acceptance.
This phase must not merge, deploy, apply, hold timers, interrupt gateways,
solicit test notes, replay historical messages or sends, reopen completed
source lanes, or allocate nested recovery requests.

Configuration base: `185a3bad139004958a0dbbfe75eeba53e39e4489`.
The only configuration change is Owl's `nest::app::hermes::git_commit`:

- Installed Native: `999c078f84b421dca53ec22e2fadcc5c795dd589`.
- Selected Native: `f5e135a8a8a66633f25d2de73f4f5e8598ce1a04`.
- Unchanged installed Broker: `96b376d7402c6bb77e6f438d1870f5f747a24f72`.
- Unchanged branch `nest`, external ownership `pm_enabled: false`, profile
  policies, overlays, credentials and unrelated configuration.

The selected Native is application !145's merge, with parents equal to the
installed Native and reviewed application source
`dc741babef8f730bbdbade87bfae0abe4e90692c`. Its tree equals that reviewed
source. The full installed-to-candidate delta is eleven files: Telegram
transport acknowledgements, their Native settlement plumbing, regression
fixtures and release documentation. No unrelated Native composition is
selected. Recheck ancestry, immutable tree identity and the complete delta
before rollout; do not replace this SHA with a newer floating tip.

Original source provenance is lifecycle event 862 / Native event 427866,
registration 427486, control !146, pipeline 13506, required job 60065.
The retained source qualification has all twenty cohorts; appended coverage
reports 1201 passed and three skipped across 115 files. This is overlapping,
trace-backed remote file coverage, not unique-case remote JUnit. Preserve the
prior red local run and concluded mixed canary. Configuration validation and
its exact-head CI are separate release gates, recorded in this task's handoff.

This correction records content-free prospective returned outbound identities
and reply routing. It cannot restore missing historical IDs, prove historical
cancellation/custody, resolve unknown sends or establish missing busy speech,
forwarded-input and multiple-follow-up conversation acceptance.

## Observed runtime and maintenance limits

Fresh preparation checks found the installed tuple above, Talon's actual
`hermes-gateway@talon.service` active, the real system `puppet-run.timer`
active and `puppet-run.service` inactive with no queued job. Both this source
worker and a peer worker were running. These observations are not a safe
maintenance checkpoint and must be refreshed by the original rollout owner.
The incorrect guessed names `hermes-talon.service` and `nest-puppet.timer`
returned inactive and are not evidence about the real units.

Owl shares Native and Broker among Talon, Star, Beryl and Quill gateways,
dashboards, pollers and workers. Ordinary Puppet convergence can refresh all
these consumers. This is conventional maintenance, not a lossless hot handoff.
Old-process media/download/debounce and outbound acknowledgement races remain
possible until intake stops. Inspect the actual installed cold-boot Telegram
queue policy; never silently change it or promise offline retention. A future
core's fences cannot protect its own first installation. Keep all SQLite/WAL,
private media, credentials, sessions, journals and uncertain-effect receipts.
No history reset, queue clearing, forced resend or replay belongs in rollout.

## Independently executable ordinary rollout plan

Only the original owner may execute this later phase under its retained
completion scope and applicable exact operation authority. This document is
not new consent and does not request another owner prompt. If a genuinely
new availability tradeoff is outside existing authority, stop at that boundary
rather than inferring approval or creating recursive repair work.

1. Read the canonical open configuration MR and exact source head from this
   task's handoff. Authenticate its full required CI and changed paths. Recheck
   current main, installed Native/Broker, Native ancestry and full tree delta.
   Stop on unrelated drift. Independently read actual worker/gateway activity
   and retained uncertain operations, including the rollout owner's own turn.
2. Keep the MR unmerged until activation is eligible. Before making a changed
   pin eligible, inspect system `puppet-run.timer` and `puppet-run.service`,
   their enabled/active state and queued jobs. If the original operation has
   authority to hold the real trigger, record its prior state and hold it;
   otherwise retain the unmerged MR. A successful noop is not a timer fence.
   Do not stop peers or clear native ownership to manufacture quiescence.
3. Use an accepted Nest project checkout with its own dependencies. From that
   exact root run these read-only preflights and retain cwd, inventory,
   modulepath, command, stdout/stderr and return code privately:

   ```sh
   bolt module install
   bolt inventory show owl --detail --format json
   bolt command run 'id -un && hostname -f' --targets owl --stream
   ```

   Expected transport is joy with Bolt escalation for root actions. No direct
   SSH or ad-hoc Puppet fallback is permitted. Diagnose exact Bolt evidence
   before a retry.
4. Once the original owner's gates permit merge, merge only the reviewed
   exact head. Verify the resulting main tree and its required CI. Deploy
   through the ordinary existing plan, then verify the served version:

   ```sh
   bolt plan run nest::puppet::deploy backend=prod environment=main
   bolt plan run nest::puppet::run targets=owl environment=main noop=true --stream
   ```

   Independently inspect the actual last-run report: exact configuration
   version, noop marker, failures, complete drift and restart notifications.
   Stop on undeclared changes. This preparation executes neither command.
5. Establish a genuine known-work checkpoint and any already-authorized input
   pause. Prepare one bounded independent user-manager unit outside gateway
   and worker cgroups. Bind its unique operation ID to original ^2341 and the
   accepted configuration SHA. Complete authenticated CI reads before launch;
   pass the existing KUBECONFIG and managed profile identity paths explicitly,
   never secret contents. Persist a private manifest, exact cwd/argv, unit name,
   log path and source tuple before dispatch.
6. The unit's wrapper must reserve an exclusive attempt marker before invoking
   Bolt, fail closed if it already exists, and retain complete stdout/stderr,
   timestamps, invocation identity and actual terminal return code in an
   atomic durable receipt, including failures. It runs exactly once:

   ```sh
   bolt plan run nest::puppet::run targets=owl environment=main --stream
   ```

   Use ordinary plan defaults unless the original owner independently
   qualifies a narrower supported selection. Do not deploy through a custom
   checkout/apply controller. A disconnect, missing transient unit or absent
   terminal receipt is unknown, not permission to dispatch again.
7. Recover the same marker, invocation, log, container exit and receipt after
   reconnect before any action. Independently read installed exact heads,
   install stamps and Puppet-owned overlays. Probe ordinary and isolated
   imports through `/opt/hermes-agent/bin/hermes-python` outside development
   checkouts, requiring canonical Native/Broker origins and no retired PM
   roots. Verify all affected consumers and retained worker outcomes, not
   merely active units. Restore a held trigger only after verified installation
   or safe prior eligibility, and read back its original state.
8. Return installed evidence to original ^2341. Preserve unknown outcomes and
   the mixed canary unchanged. Observe only permitted fresh ordinary inputs;
   do not solicit old audio, repeat test notes or replay messages to populate
   receipts. Source/CI, actual apply and conversation acceptance remain distinct.

Rollback, if needed, is a separately controlled managed source operation
retaining the accepted safe source-sync machinery and all newer user history.
It cannot reverse external effects, recover discarded updates or discharge
uncertain sends. Do not automatically cycle gateways or rewind databases.

## Declared source qualification

Run `pdk validate`, the complete unit suite, the focused Hermes catalog/data/
launcher/backup specs and the declared Hermes install fixtures. Compile a
source-only Owl catalog in an isolated explicit environment that loads this
candidate's site, Hiera and dependency modules; require the exact candidate
version, substantial resource inventory, exact two pins and runtime ordering.
An empty default-environment compile or Puppet apply/noop is not this check.
Keep secret-bearing catalogs private and retain only sanitized receipts.
Independent exact-byte review must verify only the Native pin, this release
document and the exact Talon model expectation in
`spec/data/hermes_main_model_assignments_spec.rb` changed. The latter corrects
`gpt-6.1-sol` to the already accepted `gpt-6.1-sol-900k`; it changes no runtime
model, provider, helper/delegation assignment or other assertion. Preserve the
original candidate/base failing receipts and dependency setup failures as
history; rerun the entire declared selection rather than only the repaired
example. Required exact-head configuration CI must pass before this
source phase completes. No fabricated reviewer, same-card review lane or
production canary is required or authorized by this source preparation.
