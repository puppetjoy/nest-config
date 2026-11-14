# Firefox native observation repair

Request ^2364; implementation task `t_b4c65899`. Original Star continuation and
consumer adoption remain with ^2363 / `t_d0f9969e`.

## Release state

Source qualification is in progress. Production activation and installed
navigation plus both public readbacks have **not** passed. No production
Firefox restart, navigation replay, new diagnostic window, profile clearing,
unknown-window adoption or journal cleanup was performed by this phase.

## Actual failure, not a status diagnosis

Read-only inspection retained the original production pod UID
`ee88cea7-acab-4e5b-a0e7-d635eb5ae49e`, zero container restarts and Firefox PID 62.
The installed native session could answer `browsingContext.getTree` and
`browser.getClientWindows`. A constant expression in the already-existing
non-owner blank context also completed. The retained owner context could not
answer either a constant expression or `script.getRealms`. The shipped summary
first raised `TimeoutError` from the native WebSocket receive path. Both public
readbacks share this content-actor dependency; they are not independent
transports.

Firefox itself logged `MessageHandlerFrameParent` ping timeouts for
`script.evaluateExpression` and `script.getWindowRealms` to content actor 18.
An argument-free, bounded debugger backtrace of the blocked content process
showed its main thread in `sem_timedwait`. Its semaphore address belongs to a
`mozilla-ipc` shared mapping. Disassembly of the caller matches the
`CanvasDrawEventRecorder::WaitForCheckpoint` loop: processed-count/checkpoint
comparison, writer state transitions, reader failure check and repeated timed
cross-process semaphore waits with no total deadline. Debug symbols were not
available; this identification uses the actual machine-code control flow and
header layout, not invented symbolized frames or page-memory inspection.

The earliest retained native ping warning is 2026-11-14 20:00:54 UTC. The GPU
IPC-timeout kill/fallback message maps to approximately 20:04:34 UTC using the
browser process start and its relative timestamp. Therefore the GPU kill is
**later** than the observation failure; it must not be presented as the action
that initiated it. A stalled canvas/GPU peer can strand the content main
thread while chrome/tree/status commands remain responsive. The underlying
reason that the production GPU peer first stopped progressing is not established
by this evidence. The defunct GPU process or journal size alone proves neither
that reason nor an OOM.

## Deterministic native reproduction and targeted mitigation

`spec/app/hermes/firefox_canvas_observation_canary.py` runs only in a disposable,
network-disabled copy of the installed immutable image, with fresh synthetic
profile data and no owner mounts. It creates a synthetic Canvas2D, verifies a
red pixel, stops only that container's GPU peer, then draws/reads a blue pixel.

- Baseline: the actual native content observation times out after 10 seconds.
- Setting `gfx.canvas.remote=false` alone did not fix the failure; that
  experimental setting is not included in source.
- Setting only `gfx.canvas.accelerated=false` makes the same stopped-peer pixel
  read complete with the correct value in approximately 1 millisecond.

The managed enterprise policy now locks that single accelerated-Canvas2D
preference off. Canvas remains usable with local/software drawing; this does
not disable JavaScript, WebGL, browser sandboxing, authentication or Joy-directed
workflow authority. It avoids the demonstrated synchronous accelerated-canvas
failure path rather than claiming to repair every GPU/driver defect. It does
not unstick an already-blocked production content main thread.

The candidate native canary also performs one real local HTTP navigation while
the synthetic GPU peer remains stopped. A fixture deliberately loses the
already-executed native navigation response before the controller receives it.
The original result remains uncertain. The actual public snapshot and summary
handlers then independently execute their shared native snapshot path and read
the expected fixture title from the same context/window. The local HTTP server
records exactly one navigation request: there is no replay. This exercises real
native Firefox and the public result handlers, with an isolated in-process
bridge seam; it is not production HTTPS/installed-consumer acceptance.

One expanded canary invocation reached all assertions but timed out on Python
shutdown because its reconnected observer had not been closed. The corrected
harness explicitly closes that disposable observer before stopping its launcher;
the fresh rerun exited zero. The earlier timeout is not counted as a pass.

## Preserve late creation receipts after finite wait exhaustion

The later parent task-window creation failure is distinct from the original
owner navigation. Its journal retains no native identity, despite a separate
existing blank context in the native tree. That tree difference is not ownership
proof. No production creation has been retried or retrospectively adopted.

The old bounded recovery closed the only observer after its extra receipt wait.
That loses any later correlated creation reply even if Firefox eventually
recovers. The focused regression first failed on this exact close. The repair
retains the observer and pending receipt, records finite-wait exhaustion, and
allows only nonblocking queued-frame inspection after exhaustion. It bounds
unrelated-frame drainage too. Other commands cannot restart a full wait, send
past the pending creation, adopt an unmatched reply or replay input. Only an
exact correlated receipt can establish ownership. Process death or an already
closed historical observer still cannot reconstruct a missing receipt.

The runtime input journals, generation fences, closed-scope tombstones, owner
window protections and exact native identity checks are unchanged. No old
uncertain action is reclassified as delivered.

## Managed Star contract

The Puppet source skill and public descriptions now state the v3 model:
immutable dispatcher task scope, shared persistent profile/session, separate
request window, preserved owner window, CSS selectors/viewport coordinates and
bounded query expressions. Legacy AX locators are not v3 input targets. Status
and lifecycle status/recover do not allocate; snapshot/summary/navigation may
initialize their binding. Neither status nor successful binding reconciliation
proves page/purchase completion. Recovery is no-replay, finite and engineering
owned. Existing Joy workflow authority and owner-only sensitive capture delivery
remain intact; no redundant purchase approval gate is added.

Parent follow-through must load the newly managed skill in Star's real consumer
context after ordinary Puppet installation. This phase does not edit Star's
runtime profile directly or make the parent's original retailer continuation a
prerequisite of source completion.

## Executed source and image qualification

- Controller/adapter source: `06bafb4afbe24b8eca87c57433ab3cc0510695de`.
- Its exact-head MR pipeline 13415 passed all nine required jobs, including
  Validate, Unit Test, both browser fixture lanes and Native authority fixtures.
  The later immutable image-pin/configuration commit requires its own pipeline;
  the task thread carries that final exact-head receipt.
- Containing local window/recovery/consumer selection: 175 tests and 25 subtests
  passed. All ten existing compatibility scripts and the Node viewer passed.
- The inventory-backed Owl smoke succeeded as `joy`; there is no SSH transport
  blocker. `bolt module install` kept project dependencies inside this worktree.
- The managed `nest::build::firefox` plan built from the exact installed baseline
  with frozen Gentoo, Nest overlay and Haskell revisions, then passed smoke.
  Initial publication lacked the wrapper's registry credentials and was denied.
  Publication-only retry used Talon's existing profile credential privately with
  an ephemeral auth file and the standard `files/build/publish-image.sh` helper;
  no source, package or browser operation was repeated to repair that failure.
- Candidate remote digest, independently retrieved and pulled back:
  `registry.gitlab.joyfullee.me/nest/tools/firefox@sha256:1ae6d01507ed8dd85a67f86fb9bf0f81b77fe2ad416e5f11675487dd7374ff12`.
- Candidate image config:
  `0433eedccca7682422ef9d6ef19fba71af71fe14d2721dd9c80a25cd31bb0fac`.
- Baked controller SHA256:
  `589411fc2c3efc83e3836506a55ea33e5d76e65e6718c01a3e6f3c985e20046b`.
- Baked private transport SHA256:
  `1614b6ebc3d0784591dd86e7078fe30f97124dcec8479a913dbcbfdc5b46088f`.
- The pulled-back baked candidate passed the disposable stopped-GPU canvas and
  uncertain-navigation/both-public-readbacks canary with no runtime source overlay.

Fresh allowlisted journal inspection found all 438 current native actions
marked delivered, but also two unresolved **historical** legacy action records:
one `delivery_started` and one `delivery_uncertain`. They must never be silently
replayed or omitted from generation safety. The supported generation consumer
was exercised on private journal copies with an explicitly synthetic future
process/readiness provider and synthetic grant, not live authority. It preserved
closed tombstones and all no-replay keys, archived rather than adopted the
unknown creation, and left live journal hashes unchanged. Real execution still
requires the exact trusted typed decision and fresh journal fingerprints.

## Activation boundary

A controller-only overlay cannot repair the already blocked content main thread
or apply startup policy to it. Normal KubeCM Firefox deployment uses singleton
`Recreate`, so activation needs a fresh scoped owner decision after the exact
source/image/CI candidate is available. That decision must disclose the browser
interruption, possible unsaved page-state loss, profile/journal retention and
native-generation retirement. It must also explicitly cover the existing unknown
creation rather than smuggling abandonment into an ordinary controller refresh.
Fresh safety reads must check every journal for unresolved input, verify backups
and the exact accepted source tuple, and preflight the supported local
reconciliation consumer before any stop. No old approval is reused. If those
gates fail, preserve the running browser and evidence without replay.
