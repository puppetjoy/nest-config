# Firefox public coordinate input repair

Request ^2370; worktree task `t_911665da`.

## Cause and preserved history

The published `secure_browser_click` and `secure_browser_type` schemas accept
coordinates as an array `[x, y]`. Their handlers pass that representation through
the authenticated HTTP transport unchanged. The resident v3 controller accepted
only an object `{x, y}`. It raised `ValueError` before element preflight, action
journal reservation or native `input.performActions`. The endpoint's conservative
fallback converted that exception to `FIREFOX_OUTCOME_UNCERTAIN`.

The exact reported key `winter-dismiss-newsletter-1` is absent from the installed
native journal; the installed adapter and controller match the inspected source.
A disposable real public-handler/TLS/controller/native reproduction fails with
the same error. This establishes the first failing boundary, not a native click
acknowledgement failure. The original public uncertainty remains historical;
this repair never invokes the original action, changes its key or rewrites its
history. No retailer page/account/payment data is retained here.

A second native regression demonstrated that even accepted coordinate objects
were silently recentered on the hit element. An event at requested `(110, 95)`
arrived at `(160, 110)`. Coordinate input now preserves the requested point;
selector input retains its existing rendered-element center calculation.

## Narrow repair

Normalize the public two-element array locally, after computing the existing
payload digest. Retain historical object callers and unchanged payloads/digests.
Reject malformed coordinates with an explicit pre-input refusal. Keep element
identity, obstruction, protected-field and viewport checks. Do not relax action
journaling, duplicate refusal, generation/ownership or creation receipt custody.
The accelerated Canvas2D policy is unchanged.

## Verification boundaries

`spec/app/hermes/firefox_public_workflow_canary.py` runs only in a disposable
Firefox image without owner mounts. It uses the real published schemas and
registered public handlers, adapter, authenticated certificate-verified TLS,
HTTP handler, resident controller, private BiDi transport and native Firefox.
Only registration infrastructure is a stand-in; no successful browser result is
mocked. Synthetic HTTP fixture content is loopback-only. The runner must use
`--network none`, an isolated filesystem and `FIREFOX_DISPOSABLE_CANARY=1`.

Coverage includes navigation, snapshot/summary, blocked-selector preflight,
coordinate overlay dismissal at the exact requested point, selector click,
non-sensitive typing with separate readback, scrolling, bound-window continuity,
server-observed synthetic cookie continuity, lost native acknowledgement and
interrupted HTTP delivery. The latter faults execute real input first, then lose
its acknowledgement at the declared seam. The fixture server independently
counts effects. Unknown journal entries remain unknown; repeated keys never
execute again. Recovery keeps observation and later distinct safe operations
usable. Cleanup releases only the synthetic bound task window and stops the
whole disposable container.

The original RED receipts precede implementation. An initial harness attempt
failed while examining the disposable extension first-run tab; it did not reach
the coordinate defect. The corrected disposable-only first-run preparation
matches the existing native canary. A later scroll assertion expected an element
beyond the requested scroll distance; that failed fixture assertion is retained,
not counted as a passing workflow. The final workflow uses an adequate bounded
scroll and asserts the element is visible.

Permanent coordinate-shape and invalid-input tests run in the existing required
window-fixture CI lane. Native workflow receipts are separate from unit/CI and
from installed acceptance. See the final profile-owned engineering report for
exact source/CI, activation, installed smoke and cleanup status; this source
note does not claim production activation or complete installed acceptance.
