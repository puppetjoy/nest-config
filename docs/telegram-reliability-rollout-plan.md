# Telegram reliability managed rollout plan (source preparation only)

## Scope and immutable composition

This document accompanies source preparation for ^2375 and original incident
^2341. Approval apr-20261115-034225-b3b2d0 permits this configuration
preparation only. It does not permit merging this configuration, deploying
code, applying Puppet, restarting services or running a live chat canary.

The sole runtime configuration delta is in `data/host/owl.yaml`:

- Native before: `b1044011c49860250ea3458405e0e9a93f469e6a`.
- Native candidate: `63e658d95bf61857b762e05563285c9e1dd4032b`.
- Broker unchanged: `496fdd0a453c8b11044f96514985c652025bf588`.
- Native branch remains `nest`; external runtime ownership remains enabled
  through `pm_enabled: false`.

Fresh remote reads established the configuration base as
`38eed881d49cf90ae82ba25f516888395c7b6846` and Native `nest` at the
candidate. Git ancestry proves the installed Native is an ancestor of the
candidate; the candidate tree exactly equals approved application source
`cf4c08564fc9af1e264ec5b6ee8638db70e266e0`. The installed Broker and
configuration pin agree. Broker remote main was independently observed at
`54989691d719be9a853d7c48cddea82c3f67f5ac`; this preparation deliberately
does not select that uninstalled newer head or change Broker.

The complete installed-to-candidate diff has 23 paths: conversation code,
regression fixtures/tests and release documentation. It preserves accepted
main-chat retirement and the installed baseline. Optional maintenance
commits occur in ancestry but are excluded from the final minimal tree;
ancestry alone must not be presented as active maintenance protection.
Application source CI is pipeline 13447, required job 59631; configuration
CI must independently qualify this MR's actual exact head. Neither receipt
is installed acceptance. Preserve failed historical pipeline 13445.

## Affected consumers and observed runtime

Owl's shared installation serves Talon, Star, Beryl and Quill. All four
profiles have gateways and dashboards enabled; all four gateway units were
observed active. Source/installation changes can refresh these consumers,
not only Talon's Telegram conversation. The installation is shared with
pollers, background commands and running workers.

A fresh isolated Python probe resolved:

- Interpreter: `/opt/hermes-agent/venv/bin/python`.
- Native: `/opt/hermes-agent/src/gateway/__init__.py`.
- Broker: `/opt/hermes-agent/agent-request-broker/src/agent_request_broker/__init__.py`.

The checkout heads matched the before tuple above. This is fresh-import and
checkout identity, not proof of every already-loaded module in every old
process. Observed gateway invocations were Talon
`b9c5efed46e6401f84c870d137ae7f71`, Star
`72980a5a81c54c269ec08d79e4eb397c`, Beryl
`a9a24158bfc54cc39803f75de3866f77`, and Quill
`128ceb4607aa4cc5a109a09191f2aa92`. Refresh these observations before
any future operation rather than using them as release authority.

## Real interruption and intake risks

This is a conventional managed maintenance proposal, not lossless bootstrap.
The old core keeps receiving updates until its actual intake stops. A chat
that appears idle is not an atomic fence: a voice download, media debounce,
PTB queue, busy-event merge, pending transcript or send may already be in
memory. Killing/replacing the old process can lose such uncommitted state.
A terminal answer whose send acknowledgement is lost remains uncertain;
its existence does not authorize repeating inference, tools or delivery.

The candidate fixes terminal-media collection blocking delivery/FIFO,
forwarded-input context and late-generation final delivery. It does not
retroactively protect the old process's intake or establish a whole-system
maintenance admission boundary. A new-core fence cannot protect first
installation of itself. Gateway units use KillMode=mixed and a 210-second
stop timeout; independent workers are not thereby proven uninterrupted.
Wait for known work to finish and inventory retained attempts; do not cancel,
reset or replay a running/unknown operation merely to make a quiet window.

Both inspected source and candidate use `drop_pending_on_cold_boot`, default
true. Fresh reads of all four profile configs found no explicit override.
Thus an ordinary process cold boot can discard Telegram's offline queued
updates; watcher reconnect uses a separate preserve policy. Disabling that
policy would be an additional configuration change and may expose old queued
commands to execution: it is NOT included in this one-pin preparation. A
future approval must explicitly accept the observed cold-boot policy and
planned pause, or require a separately authorized alternative before apply.
Do not promise offline retention or silently change the flag. Pause new owner
inputs across affected profiles for the agreed window. This reduces but does
not eliminate the old-core in-memory race.

Keep profile histories, SQLite databases/WALs, retained private media,
credentials, worker receipts, sessions and journals in place. No queue
clearing, media deletion, history reset, raw state surgery, historical input
replay or forced resend is part of rollout or rollback. Existing admitted
work may recover through its native owner; inspect exact admission and
settlement identities before treating recovery as permission to execute.

## Future ordinary rollout: independent owner and exactly one attempt

The following is a plan, not an instruction executed by this phase.

1. Obtain separate Joy approval binding the exact reviewed configuration
   head/merge, Native/Broker tuple, affected profiles, conventional interruption
   and offline-update tradeoff. Recheck all heads, ancestry, required CI and
   installed tuple. Stop on drift rather than reusing this approval for a
   newer Broker or Native. Preserve ^2350's terminal history.
2. Before making an approved pin eligible to automatic convergence, inventory
   the real Puppet timer/service state and in-flight applies. Either retain
   the MR unmerged or obtain authority to hold the actual trigger. Record its
   original enabled/active state. A noop is not a timer fence. Do not publish
   into main while activation must remain unauthorized.
3. From the accepted project root with its own declared Bolt modules, verify
   `bolt inventory show owl --detail --format json` and
   `bolt command run 'id -un && hostname -f' --targets owl --stream`.
   Expected transport is joy with Bolt escalation, not direct SSH. Capture
   exact cwd, inventory, modulepath, command, stdout/stderr and exit privately.
4. Merge only after exact approval and fresh release checks. Require resulting
   main CI and verified merged tree; deploy code through
   `bolt plan run nest::puppet::deploy backend=prod environment=main`.
   Verify the served environment's exact version. Run inventory-backed
   `bolt plan run nest::puppet::run targets=owl environment=main noop=true --stream`
   and independently inspect the real last-run report's version, noop marker,
   failures, unrelated drift and restart notifications. A plan exit alone is
   insufficient. Stop if scope differs from the approved tuple/interruption.
5. Prepare one durable independent execution owner under the user manager,
   outside the gateway and worker cgroups. Use an attempt identifier bound to
   original request, exact configuration head and a unique operation ID. Store
   a private manifest with cwd, argv, source tuple, unit name, environment paths
   and approval reference. Perform authenticated GitLab/CI checks before
   launching the credential-free unit; pass the existing KUBECONFIG path and
   managed profile SSH identity explicitly, never token contents.
6. The unit wrapper must atomically create an exclusive attempt marker before
   Bolt dispatch (for example noclobber creation with failure on existing
   marker), preserve complete private stdout/stderr, and persist a terminal
   receipt with actual return code and start/end time even when Bolt fails.
   Use a finally/exit trap and atomically publish the completed receipt; do
   not rely on a transient unit surviving garbage collection. Record the unit
   invocation and container identity. A missing receipt is unknown, not a
   reason to dispatch again. Repeated starts must fail before a second apply.
7. After the approved input pause and fresh known-work checks, that one unit
   runs ordinary
   `bolt plan run nest::puppet::run targets=owl environment=main --stream`.
   No ad-hoc Puppet, manual source checkout or parallel cutover controller.
   Ensure fixed post-apply verification and trigger restoration responsibility
   survives a chat disconnect. Preserve the hold on unknown/failed gates; do
   not silently restore automatic eligibility to an unverified candidate.
8. On reconnect, recover the SAME attempt's marker, unit invocation, complete
   output and exit receipt before any action. If the unit disappeared, inspect
   its retained receipt/journal/container exit, not a new apply. A missing unit
   is neither success nor failure. Never resend the deployment to find out.
9. Independently read installed Native/Broker heads, install stamps and owned
   overlays. Probe fresh ordinary and isolated Python imports through the
   managed launcher: require exact source origins and no retired PM import
   roots. Verify all affected service generations and real last-run report.
   Verify worker ownership/terminal outcomes from retained receipts; do not
   infer full history equality from inode continuity or service readiness.
10. Restore any explicitly held trigger to its original state only after
    verified completion or safe prior eligibility; read it back. Keep failure
    and restoration ownership durable. Report actual installed evidence to
    the original incident owner without replaying historical actions/sends.

Rollback is a separately controlled source-managed operation, not automatic
rewind of user databases or chats. It cannot undo external tool effects,
recover discarded offline updates or resolve uncertain sends. Preserve all
new history and unknown outcomes, and obtain authority for any disruptive
rollback rather than repeatedly cycling gateways.

## Acceptance and boundaries

This preparation releases only when source review, configuration validation,
containing checks and required exact-head CI pass, with the exact open MR and
head returned. The supervising owner is also implementer, so no fabricated
reviewer or same-card implementation-review workflow is required. Keep the MR
unmerged. Historical cancellation attribution/audio custody and the original
installed direct/forwarded multi-turn speech/relevance, progress/crash and
uncertain-send gates stay with ^2341. Controlled STT fixtures, a clean apply or
healthy services do not satisfy those gates. No new repair requests or nested
work are authorized by this preparation.
