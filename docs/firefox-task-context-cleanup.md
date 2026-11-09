# Task-owned Firefox context cleanup

Request ^2354, task `t_679195ea`. Nest is the integration owner; the existing
Broker source prerequisite is ^2355 / MR !249. This is a source and disposable
native acceptance report, not a claim of production deployment.

## Diagnosis

Joy reported closing four or five accumulated Muse contexts and the observed
rendering load disappearing. That is owner-reported intervention evidence, not
proof of an exact historical callback or a same-process CPU differential.

The first investigation found two Done scopes stuck in `closing` after a
single failed delivery, and an Archived scope with an open binding but no close
obligation. The installed controller matched the inspected Nest baseline.
The previous tests covered an ideal terminal callback, not these real gaps:

- `release` was accepted but ignored; releasing an unallocated scope actually
  created a window.
- The resident controller ignored task lease duration and `keep_open`.
- An exact already-absent context could not be acknowledged while its binding
  still said `open`.
- A failed exact close could never retry even after same-session readback
  proved that exact context still existed.
- Closing only the original context did not clean up native opener descendants.
- Broker delivery depended on selected hooks, not its existing periodic service.

These are reproduced defects. They do not establish which historical Muse
operation originally leaked a context.

## Durable controller contract

Task creation receives an ephemeral 1800-second lease. Valid task operations
renew it. Explicit `acquire` or `keep_open` may specify an integer duration from
60 through 86400 seconds; `keep_open` requires that duration. Ordinary activity
does not shorten a longer explicit lease. Status observation does not renew or
allocate a task window. The pre-existing owner binding never expires, and old
active bindings without a lease are not aged into abandonment.

The existing resident HTTP server checks cleanup every five seconds, including
when no task or model is calling it. It takes the same endpoint exclusion lock
as task operations and the same reentrant controller lock as lease renewal.
The advisory pending check does not own eligibility: sweep rechecks deadline
and exact close intent under that shared lock. A renewal committed before sweep
eligibility wins; an expiry claim already closing a context fences later input
and renewal. A dead/disconnected worker cannot make an ephemeral lease last
forever, but disappearance is not fabricated canonical task completion.

Normal healthy cleanup targets a five-second tick after expiry or retained
terminal/release intent. At most four scopes are processed per tick; uncertain
failures have ten-second backoff and stop automatic reconciliation after three
failed passes. Native close delivery is independently capped at three attempts
per exact context, durable before sending. This is not an unconditional
wall-clock guarantee during native transport stalls or identity loss. Exhausted
or unknown state stays journaled for bounded operator recovery; no replacement
window, URL matching, profile reset or uncertain input replay is allowed.

`release` closes an existing exact task binding, never allocates, and cannot
close the owner. A later canonical terminal receipt can attach to a proven
release/expiry tombstone; conflicting event identities still refuse. Terminal
intent fences further task input even if native closure is temporarily blocked.

Close is idempotent, unlike UI input. Every attempt re-reads the retained native
session and requires exact context/window identity. Already-absent identities
are acknowledged without another native close. Native `originalOpener` lineage
proves page-created secondary tabs/windows; discovered lineage is journaled
before closing ancestors. Foreign tabs, moved contexts, overlapping scope/window
identities and excessive descendants refuse cleanup. No ownership is inferred
from title, URL, a new window appearing or tree subtraction. Missing native
lineage is not guessed. Browser-session generation loss retains the existing
explicit operator reconciliation requirement; observer-only restart resumes the
same native session and pending close intent.

## Broker integration

MR !249 at `62fc1532648e6e93429a2f67e661957a20cef92e` was freshly read back as
open, draft and unmerged with successful exact-head pipeline 13187. Its source
phase reports reviewed maintenance cancellation/archive staging and durable
bounded service retry before provider work. Nest prepares that independent
Broker pin without changing the accepted Native core pin. Existing Talon/Star
source-managed lifecycle enablement is already present; installed poller boot,
periodic service environment and credentials still require deployment acceptance.
No historical journal/outbox rows were rewritten.

## Executed source and native evidence

The original four cleanup reproductions failed against untouched runtime. The
additional explicit lease, expiry and native-opener fixtures also failed before
their implementation. Final focused containing execution passed 166 tests using
32 xdist workers and system Gentoo Python. The existing Node target-guard/window
viewer suite passed. The compatibility environment is explicitly
`SECURE_BROWSER_CONTROL_MODE=firefox-ui-v1`; an earlier inherited-v3 run and a
mistyped environment selector are retained failures, not passes.

The first parallel HTTP run exposed unnecessary janitor endpoint-lock contention
with no eligible work. The janitor now avoids taking the endpoint lock when its
query-only pending check finds no eligible work; the complete parallel rerun
passed. A first independent review alleged a renewal race; a fresh semantic
review traced the actual common RLock and rejected that allegation. Two durable
concurrent tests exercise both orderings. The final runtime/test/CI hashes were
reviewed with no blocking semantic finding. This is independent source review,
not independent production acceptance.

The disposable native canary used the real managed Firefox/Kasm image with only
reviewed controller source overlays, no user mounts and networking disabled.
It exercised real continuously rendered frames, four successive task-like
rendered workflows, exact native popup lineage, same-session observer restart,
release, completion/cancellation receipts and independent server-loop expiry.
Final native run:

- Four rendered contexts produced 228, 217, 199 and 183 real frames.
- Container process CPU was 2.0 percent before, 283.12 percent during rendering,
  and 0.5 percent after exact task cleanup.
- CPU uses same-PID-and-birth surviving processes within each two-second
  interval. It is disposable synthetic evidence, not production Muse evidence.
- Native popup `originalOpener` was proven and its exact cleanup survived
  observer reconstruction.
- Periodic expiry returned the departed scope to baseline in 1.405 seconds
  without another task/readback/sweep call, preserving a 3600-second renewed
  scope and the synthetic owner. Final native context count was one.

Earlier native fixture setup runs are not passes. One ran before the driver was
ready; another encountered a fresh Bitwarden welcome tab without an opener and
correctly refused to claim it. The final disposable setup waits for first-run
initialization before declaring its synthetic owner baseline. It must never be
used to close arbitrary initial contexts in a production profile.

## Transport and optional GPU findings

Initial Bolt inventory failed before transport because the isolated worktree
lacked `ruby_task_helper`. `./bin/bolt-wrapper module install` installed declared
local modules; inventory and `command run 'id -un && hostname -f' --targets owl
--stream` then passed as joy on owl. No direct SSH or ad-hoc Puppet fallback.

Inventory-backed read-only discovery identifies Owl's AMD render node as
`/dev/dri/renderD128`, PCI `0000:c2:00.0`, vendor `0x1002`, device `0x1586`,
`amdgpu` driver. Owl advertises three shared `squat.ai/gpu` slots; llama-qwen
currently requests/limits one. Firefox has no GPU allocation or render-device
mount. The existing shared device allocation includes `/dev/kfd`, so it is not
a render-only least-privilege contract. Disposable Xvnc also reports missing
DRI3 hardware acceleration. GPU rendering is not qualified or deployed; no
GPU preferences, model resources or reduced-motion settings were changed.
That complementary work is not a lifecycle release dependency.

## Remaining release and installed acceptance gates

Exact-head Nest CI, ordinary source release approval, managed Firefox image
build/publication and verified registry pull-back remain required. Install the
accepted Broker source through normal managed Owl apply; verify the actual
periodic service's installed source and enablement. Update the durable KubeCM
image baseline and use the supported image-extracted controller-only refresh
where it avoids an unnecessary singleton Firefox/profile restart. Normal
explicit rollout gates remain in force. Do not turn source evidence into consent.

Before claiming delivery, verify installed controller/image identities, actual
task-tool acquisition/release and canonical terminal delivery, bounded cleanup
without a finally/readback trigger, exact native baseline and unchanged owner
contexts. Keep authentic installed task/run acceptance distinct from the
controlled-clock disposable lease fixture. Preserve login/session state,
working active scopes, unknown windows and all journals. No production
controller refresh, browser restart, source merge or managed apply has occurred
in this source preparation phase.
