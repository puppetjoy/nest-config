# Firefox scrolling, text continuation and owner window visibility

Request ^2378, task `t_c4f1d4b6`. This is a source candidate, **not an
installed repair**. Production must not be restarted or silently changed to
activate it. The previous delivered repairs ^2363, ^2364 and ^2370 remain
historical; this recurrence does not rewrite their outcomes.

## Preserved recurrence

Star comment 29251 on `t_d0f9969e`:

> Fresh Joy-directed Amazon Native restock test: navigation to order history and coordinate click to exact deodorant product succeeded. However secure_browser_scroll down amount=1 and then amount=2 both returned ok while successive viewport screenshots remained at the same top-of-page position, leaving Add to Cart below viewport. A subsequent paginated secure_browser_query read of #buybox returned FIREFOX_OUTCOME_UNCERTAIN. Bounded lifecycle recover returned verified/open binding, not page/action completion. Browser generation 35108549df2748b6475aa084222a8d64c7ff4ba49484fc21; scope owner. No cart-add or purchase actions issued. Window preserved. Please investigate scroll no-op and query continuation failure; no browser restart requested.

Nonallocating public status in this worker verified the same generation, protocol
`firefox-windows-v3`, installed controller SHA256
`38cb671a38a0919a580b17844df91d7e1e0b0f133eea979cbf0581861c676371`,
and adapter SHA256
`312dfdb6b2722f00a1ffea864ee81fca676cecb9a541ffb7bff10594a0cda5fb`.
No owner-window page observation or input was used for investigation. The worker
has not replayed Star's actions, read private retailer text, or changed carts.
Status is not a recovery receipt.

## Ranked hypotheses and falsification

1. The hard-coded wheel hit point `(10, 10)` reaches fixed/sticky UI instead of
   the intended scrolling surface. A wheel-cancelling fixed header should cause
   successful native acknowledgement with zero scroll geometry change.
2. A changed text revision causes the continuation cursor validation to raise
   `ValueError`, which the generic HTTP error boundary mislabels as unknown
   action execution. A synthetic DOM change between pages should reproduce it.
3. Window routing or focus changes direct input elsewhere. Separate bound-window
   geometry and foreground observations should distinguish it from hit-testing.
4. A native transport stall causes the read failure. Deliberately lost native
   and HTTP acknowledgements must remain distinguishable from cursor invalidation
   and preserve journals, observation and later safe operations.

The real registered public handlers, certificate-verified TLS, HTTP controller,
private native transport and disposable Firefox reproduced hypotheses 1 and 2
against the exact installed controller bytes. The scroll returned `ok` while
both root and nested positions remained zero. The changed-cursor query returned
`FIREFOX_OUTCOME_UNCERTAIN`, `outcome=uncertain`. These are causal reproductions
of the reported failure shapes, not proof of the exact private Amazon DOM or
its first query exception. That original native exception remains unknown;
Star's original uncertainty is retained unchanged.

## Corrections

- Select a viewport hit point by observing its innermost scrollable ancestor,
  preferring the largest reachable scroll surface. Root and nested containers
  use the same path. Send one native wheel event, never scripted scrollTop
  mutation or automatic alternate-point replay. Report same-container geometry
  as `moved`, `at_boundary` or `no_movement`; a successful input acknowledgement
  or title/URL summary is not movement proof. A boundary sends no wheel.
- Return `FIREFOX_TEXT_CURSOR_STALE`, `outcome=not_started`, for changed/invalid
  continuations. Preserve that typed error through endpoint and public adapter.
  Restart observation with the same expression and no cursor, discarding old
  pages. Redaction still precedes slicing. True native/HTTP transport uncertainty
  remains uncertainty, with the operation explicitly identified as `query`.
- Request native sessions with `unhandledPromptBehavior=ignore`. Owner viewing
  must not implicitly accept or dismiss a browser security/native dialog.
- Keep coordinate point preservation, protected-field preflight, Canvas2D policy,
  late creation receipt custody, immutable bindings, generations and no-replay
  journals intact.

## Owner switcher and trust boundary

The root ingress serves the existing KasmVNC desktop; the capability viewer is
not the root and has no directory. History contains the same-session viewer,
not a previously implemented owner switcher. Do not broaden a per-task viewer
capability into permission to enumerate other capabilities/windows.

A small native GTK dock on the existing desktop provides a task-scoped window
selector, View, Refresh and Return to owner. It displays canonical task labels,
not page titles/URLs, and refreshes new/closed entries. It uses a mode-0600 Unix
socket in a mode-0700 directory and verifies `SO_PEERCRED` against the controller
UID. There is **no HTTP window-list endpoint**, no list operation in the agent
command envelope, no viewer capability export, and no new root authentication
or CORS bypass. It inherits the existing Kasm desktop access boundary, including
its existing LAN access configuration; this does not claim that Kasm already
has an owner-login authentication layer.

The initial implementation exposed another acknowledgement/effect mismatch:
`browsingContext.activate` and classic window switching acknowledged success but
left X focus and visible root pixels on the original window. Xmonad's background
focus policy must not be replaced with blanket EWMH activation permission.

The candidate therefore resolves the exact stored Firefox `clientWindow` through
a fixed **read-only chrome identity script**, converts its GDK top-level native
handle to an XID, verifies the browser PID, revalidates the binding, and sends a
single local owner-focus message to xmonad. Xmonad focuses only an already managed
window. The helper independently observes actual X focus before reporting success.
No URL/title/geometry matching, XTest input, replacement native session, task
acquisition, lease renewal or ownership retargeting is involved. Owner-created
native transients keep ordinary management; the fixture proves an open native
prompt survives selection.

This needs Firefox's `--remote-allow-system-access` startup flag for the fixed
private chrome identity read. It increases the privilege of the already private,
loopback-only native session. No arbitrary chrome/JavaScript or native-handle
operation is exposed to public agent tools. **This new private privilege and the
singleton restart must be explicitly disclosed in a fresh scoped rollout
proposal; source preparation is not activation consent.** The capability-bound
page viewer and its authenticated control route remain unchanged.

Agent operations remain context-bound even while the owner views another
window. The dock changes only the deliberately selected owner-visible native
window, not any agent binding. Stale/closed selections refuse, without selecting
another window or replaying input. Native protected dialogs are not accepted,
dismissed, or rendered as fake page content.

## Regression and delivery boundaries

`firefox_public_workflow_canary.py`, with `FIREFOX_SCROLL_READ_MODE=all` and
`FIREFOX_OWNER_PANEL_CANARY=1`, exercises the real public path in a network-disabled
disposable image, without owner mounts. The extension modules provide synthetic
fixtures and effect assertions, not mock successful browser responses.

Coverage includes fixed/sticky wheel-cancelling headers, root/nested scrolling,
actual geometry and synthetic server scroll observations, top/bottom boundaries,
real event cancellation/no movement, native viewport resizing, multipage text,
redaction crossing a page boundary, dynamic stale cursors, restart from page one,
native observation timeout, interrupted HTTP response and subsequent observation.
Original coordinate/click/type/cookie and lost-input-ack/no-replay journeys remain
in the containing workflow. Native GTK interactions select multiple simultaneous
windows, return to owner, observe new/closed/stale selections and retain public
background routing. Safe screenshots come only from the disposable desktop.

The required CI window-fixture selection includes the owner IPC/identity tests.
Native receipts are separate from CI and installed acceptance. Source-overlay
native runs do not qualify a baked image. Image build/pull-back, baked native
qualification, exact-head CI, fresh rollout consent, normal GitLab/Nest/Bolt/
KubeCM application, installed source/read/scroll/root-UI tests and exact cleanup
remain delivery gates. Joy's later actual use is not an engineering gate.

The Puppet-managed Star skill now requires an incident-specific first-class
request to Talon for recurrences. Comments on closed requests remain provenance,
not actionable notification delivery; no Star runtime profile was edited.
