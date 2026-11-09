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

## Managed image and installed recovery boundary

The existing `nest::build::firefox` Bolt plan built from source head
`af82bbf95693e77afacb0998f537e7e4dfa6d0b0`, using the previous exact image as
its refresh base. Its ordinary smoke passed, including the existing KasmVNC
memory check. A second ordinary build-plan invocation published the checked
container under `cleanup-t_679195ea`. Authenticated GitLab registry metadata and
an actual registry digest pull-back verified:

- Image: `registry.gitlab.joyfullee.me/nest/tools/firefox@sha256:772fde6c6253200d1ce68cd8b8f897459109a8ab980482221841c48a0af39898`
- Image config: `77e8f0c2aaca6493383daf646c3349da69b03fe42d83208ed48e2ca9ca2a08db`
- Baked controller: `d7f0277d88df507555c6acd2630691c36236bb9b719568ce1e251f6b8e9fc78e`
- Baked endpoint: `8ec7f3eb0fd2c195ef7d1abb4b245535d5909eead47f87fc2200f8ed9de71951`

Both baked hashes equal independently reviewed source. With no controller
overlays, the pulled-back image passed the native canary again: real frames
223, 211, 198 and 184; synthetic container CPU 4.0 percent before, 287.45 percent
rendering and 1.0 percent after cleanup; periodic expiry in 0.603 seconds;
retained owner/renewed scope; final context count one. This is the managed
artifact, still disposable acceptance rather than installed production proof.
The existing full native window canary also passed shared synthetic login,
input/screenshot isolation, multiline no-send, protected-input refusal, owner
viewer input, observer reconnect and exact terminal wire acknowledgement. Its
old nonterminal loop depended on ignored `release`; it was migrated to the
explicit bounded `keep_open` producer, leaving the original continuity,
isolation and terminal assertions intact. The initial old-contract run remains
a failure; the corrected canary passed against unchanged baked runtime.

Registry verification did not assume a local Podman digest alias. Host skopeo
was absent, and a host-root publication-helper invocation lacked the wrapper's
registry auth and was denied. Authenticated GitLab registry tag metadata then
identified the actual remotely served digest above, which pulled successfully.
No credential bytes were read or emitted and the denied path was not retried.

A fresh real `secure_browser_status` call returned `FIREFOX_IDENTITY_LOST`.
Read-only installed diagnostics prove a native generation change: the journal's
browser PID is 62 with generation
`aaa61ea1074c9a7cac6f37908e982843f8a3e0d46d53138febf8e4350b0fc246`, whereas
current PID 62 has generation
`b469bb92d27111d5787d1d6c8a2734d7c00bc2734d26645bf29779ea10a66a15`.
The repeated PID is not continuity. Geckodriver reports ready for a session;
no new session was created during diagnostics. The live endpoint remains baked
source, controller hash
`7e333fa0c36ba9c09d2858aa8421e2aa54a0ea674f47e3795a2156daa20bc34a`.
All 413 current window action records are delivered. The legacy journal retains
one uncertain and one started action; their exact fingerprints, not raw inputs,
were retained for the existing supported operator reconciliation contract.

Current aggregate journal SHA256 is
`319ccc2eb419ed30e6cda5d63457b206df463388965884bc4b3c37d61ee2f41b`.
Any reconciliation must freshly recheck it and the native generation, archive
the old journals, retain all non-replayable action keys and preserve every
unknown/current native context. No task can infer fresh ownership from old IDs.
This requires an explicit scoped operator decision, not a blind refresh,
profile/browser restart or silently manufactured approval.

## Remaining release and installed acceptance gates

The first Nest source head above passed exact-head pipeline 13199. Superseded
head `dfb4c86e57620b22b71894300a5e4a7ce2d1968c` passed pipeline 13201 but changed
both KubeCM image inputs. That candidate did not satisfy the promised
controller-only release: ordinary reconciliation would recreate the singleton
browser. The successful pipeline and baked-image evidence remain historical
receipts, not approval of that deployment contract.

The corrected candidate restores the complete `data/kubernetes/app/firefox.yaml`
to its original baseline. Read-only installed Deployment inspection confirmed
image `sha256:8b64b477220c6d1121f8fdc45dabb3a4d0ff854bbcb9e4a53b5266807aeaa87c`
and `NEST_FIREFOX_IMAGE_REVISION=bc61fa52bafc5c2b3f72604c1fbe27c109991844`.
Both remain unchanged. No image digest, revision environment variable or other
pod-template input in this application is advanced by this release. The new
image above is a separately retained, tested artifact, not an active KubeCM pin.
This correction requires independent delta review and new exact-head CI.

After exact reviewed source acceptance and the appropriate owner authorization,
the managed sequence is:

1. Recheck Nest and Broker exact heads, successful CI, installed image/revision,
   and complete rendered Firefox pod-template equality against the installed
   Deployment. Refuse unrelated source drift; preserving just the image is not
   enough. Keep secret-bearing render output private. Do not apply a different
   template or use an unmanaged deployment exclusion to claim restart freedom.
2. Release the accepted Nest/Broker source through ordinary Bolt/Puppet gates,
   preserving the accepted Native core pin. Managed Owl apply may interrupt
   agent gateways and controller clients briefly; admit the normal maintenance
   boundary first, retain work and do not replay unknown-outcome operations.
   Verify installed Broker source, boot/periodic service and enablement.
3. Revalidate image-extracted controller assets against the reviewed hashes.
   At the supported local operator recovery boundary, require an idle endpoint,
   exclusive controller lease, ready driver, exact old journal digest and exact
   current native process identity. Retain original journals, all non-replayable
   keys and the exact approved legacy exceptions. Retire obsolete task/viewer
   bindings without claiming their old native IDs or closing current/unknown
   windows. Refuse fingerprint drift, new uncertainty or unsupported authority;
   no raw journal edits or alternate recovery path.
4. Use `bin/firefox-controller-refresh` through the inventory-backed Bolt path
   with the exact supported recovery grant and image-extracted assets. Only the
   observer/controller is replaced. Firefox, geckodriver, KasmVNC, profile and
   user windows stay running. Controller/client access is briefly unavailable;
   failed or uncertain activation requires readback, not blind refresh replay.
5. Verify installed source and native generation, authentic task-tool cleanup,
   terminal delivery and unchanged unrelated contexts before claiming success.

The `/tmp/nest-firefox/controller-overlays` activation is pod-local, not durable
across pod replacement. This controller-only phase cannot claim a durable baked
image rollout. A separately authorized future normal managed image-pin change
and singleton browser restart are required to make the tested image the next
pod baseline. Profile storage remains retained, but live browser connections
would be interrupted by that future rollout. It is explicitly excluded here.
No GPU or motion changes are part of either controller-only recovery or its
acceptance. Source correction is not new release consent; the earlier exact
owner receipt must not be stretched to a different source head or operation.

Before claiming delivery, verify installed controller/image identities, actual
task-tool acquisition/release and canonical terminal delivery, bounded cleanup
without a finally/readback trigger, exact native baseline and unchanged owner
contexts. Keep authentic installed task/run acceptance distinct from the
controlled-clock disposable lease fixture. Preserve login/session state,
working active scopes, unknown windows and all journals. No production
controller refresh, browser restart, source merge or managed host apply has
occurred in this preparation phase.

## Native decision authority adapter (source-only continuation)

The actual failure was an authority-schema mismatch, not missing consent.
`owner_instruction_grant` inspected only the current changed-instruction
reference. Native typed Telegram approval instead records an immutable
`native_owner_decision_approved` event, the exact original hold and digest,
consumed human-blocker generation, trusted provenance and a typed operation
scope grant. Resolving that human gate does not mean Firefox recovery ran.

The helper now accepts `--native-owner-decision` with exactly these fields:

- `approval_event_id`: immutable Native approval event ID;
- `hold_event_id`: the original typed Native hold event ID;
- `blocker_generation`: the canonical generation recorded by the producer;
- `digest`: the producer's complete decision snapshot digest;
- `scope`: the complete original `owner_operation_scope` and, if present,
  `decision_scope`, structurally equal to the approved snapshot.

Use the managed `/opt/hermes-agent/bin/hermes-python` interpreter so Native
and Broker are imported from their installed canonical source roots. Keep the
existing generation request and grant arguments. There is no keyword matching,
URL/title inference, proposal fabrication or conversion of an instruction into
external-operation consent. The older instruction reader remains compatible
for context verification, but main refuses to use changed-instruction context
alone as generation-recovery authority. Proposal-approved retired-binding and
explicit administrator creation-recovery routes remain separate and cannot be
combined with generation recovery.

The new reader uses one canonical read snapshot and Native's query-only guard.
It cross-checks request/task, hold, full decision digest/scope, trusted owner
identity, canonical blocker generation, actual consumption receipt, independent
trusted origin provenance and the exact operation grant's approval ID. Missing,
foreign, altered or retired records refuse. Runtime admission additionally
refuses terminal tasks, unresolved decisions/proposals/reviews, newer approved
decisions, scheduling/review gates and newer execution instructions. Historical
consent remains inspectable but cannot bypass a later source-only instruction.

`--check-authority-only` verifies that historical receipt and exits before
reading assets or invoking kubectl. Its output explicitly says
`execution_authorized: false`. This is the supported read-only preflight for
retained approval evidence, not a deployment dry run or release grant. The
caller must still separately bind exact accepted executable source, artifact
hashes, CI, rendered pod-template equality and ordinary maintenance admission.
The opaque human-readable operation fields are compared exactly, not parsed
into commands or treated as machine-verifiable source acceptance.

Before signaling the resident controller, generation recovery now exercises
the actual final `Windows.reconcile_generation` consumer on private disposable
copies of the complete journals and matching existing archive. Only its driver
readiness GET touches the native service. Journal/archive writes remain in the
private copy; cleanup runs on success and refusal. It detects stale digest,
live generation, occupied driver, pending input, malformed legacy exemptions,
archive conflicts and filesystem failures before stopping the controller.
An already consumed reconciliation approval refuses another controller refresh;
inspect installed state instead. Existing endpoint exclusion, native/process
identity, no-replay and exclusive controller-lease gates remain in place.

Local containing tests use every logical CPU. The separate paired CI job pins
Native `df1b7bbaffb7de71db0d2a51b20bb68af616b205` and Broker
`62fc1532648e6e93429a2f67e661957a20cef92e`. It uses the real Native hold,
trusted synthetic Telegram callback and operation-grant producers, then calls
public helper `main`; only kubectl transport is doubled. Whole-database
refusal checks are distinct from native-journal preflight fixtures. None of
these tests grants release authority or proves installed browser acceptance.

Retained receipt `apr-20261109-102018-e4b8f4` names Nest source
`166a7e355797e8113c4a28de84d16b3081ecf950`. The adapter changes executable
helper bytes, not the approved operation's target or the seven browser assets.
That old receipt is preserved; it does not silently accept this additive source
revision. The supervising owner coordinates the exact changed-source release
and current installed Broker pin. Do not roll back an intervening healthy
Broker rollout by applying this historical branch's host pin. No merge, host
apply, controller/browser refresh or journal mutation is part of this source
continuation. Lifecycle remains not deployed/installed-verified; GPU remains
unqualified and undeployed.

## Closed acceptance scope correction

The preceding sections are historical source-phase checkpoints. The approved
controller-only phase and managed Broker/tool apply subsequently completed;
installed real lease expiry and low idle CPU were verified. The controller
remains pod-local. The baked serving image has not been advanced, and GPU
rendering is still unqualified and undeployed.

The required preflight for the later approved pin-only image rollout exposed a
real recovery defect: a legitimate lease-expired requesting scope was rejected
by generation reconciliation as if reconciliation must reopen that scope. The
corrected generation consumer preserves a closed acceptance binding exactly,
including its close reason, native absence evidence and terminal identity. It
continues to refuse a terminal binding that is not proven closed. Generation
recovery is not permission to acquire the closed task again; no substitute task
or guessed native identity is introduced. Unclosed unrelated bindings are
retired to immutable history rather than claimed closed, and every old action
key stays non-replayable. Existing digest, driver readiness, lost-generation,
uncertain-input, immutable archive and exclusive administrator gates remain.

Three real-producer regression variants (expiry, explicit release and terminal
close) failed at the original refusal before the runtime correction, then
passed. They verify exact tombstone/archive preservation, crash reconstruction,
idempotence, acquire/input refusal and late terminal receipt attachment without
native mutation. Additional closed-scope refusal controls cover pending input,
stale digest, occupied driver, active generation and unclosed terminal intent.
The public refresh helper's private-copy final-consumer preflight also covers
an already released scope and preserves every original journal/archive byte.

`spec/app/hermes/firefox_closed_scope_restart_canary.py` is a two-phase,
disposable-only native fixture. Run setup in a fresh network-disabled managed
image with a dedicated synthetic home volume, stop that container, then run
verify in a new container using only the same synthetic home volume. This
models pod replacement with persistent profile/journals and fresh `/tmp`, not
restarting a container with stale X-server locks. A real native generation
change is mandatory. The fixture checks exact tombstone/archive preservation,
status-only native recovery, no reopen, old active-binding retirement, fresh
native acquisition/release and unchanged unrelated identities within the new
native session. It must never be run against the production profile.

This additive executable correction is not contained in the immutable artifact
named by approval `apr-20261109-195822-55fd5f`. That approval is retained, not
stretched: successor source/artifact acceptance must explicitly include this
correction before publication/release of a changed candidate and managed
production rollout. No browser restart, production journal rewrite, action
replay, GPU change or new request is part of source preparation.
