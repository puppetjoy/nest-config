# Persistent Firefox: ordinary browsing with reusable request windows

## Observed defect

Request ^2386 (`t_5749efb3`) remained nonterminal after its Nest image-pin
children completed. The installed resident journal records its window as
`state: closed`, `close_reason: release`, with no terminal receipt. The recorded
browser epoch still matches the healthy installed controller. This establishes
window release as the closure producer; it is not evidence that child completion,
worker exit, restart or lease expiry caused that release. The journal does not
retain the release caller or timestamp, so those are not asserted here.

The release command sets that close reason and verifies native context absence.
The defective acquire path subsequently rejected every record with a close
reason. Recovery returned `next_action: none` for every closed binding. Together,
these made ordinary temporary disposal a permanent request ban.

The original application's `artifact-access-blocker.md` also retains the refused
prerequisite-routing attempts. Those remain Wizard evidence, not a prerequisite
for this independently requested browser repair.

## Conventional lifecycle

- Ordinary browser operations acquire and renew a request's window internally.
  No explicit acquire/recovery call is required.
- Release and idle expiry dispose of that window. A later operation allocates
  another window in the same persistent authenticated Firefox profile.
- Worker-run changes, waiting for children and resumption do not change the
  request key. A live window can resume through a new controller observer.
- After a proven native process-generation loss, and only with an unoccupied
  native driver, preserve the old journal in immutable generation history and
  connect normally to the current Firefox. Old native IDs are never adopted.
  The code does not restart Firefox, replace an occupied driver session, replay
  navigation/input or retire unresolved action records.
- Deliberate canonical terminal cleanup remains a fence against late workers.
  Owner windows, unknown contexts and user-retained unrelated tabs are never
  selected or closed by guessing URLs, titles or tree differences.
- Uncertain actions belong to the independent action journal, not window
  admission. Their original keys and outcomes remain intact across reuse and
  restart. They cannot execute again; distinct later browsing is not disabled.

Legacy explicit operator reconciliation interfaces remain compatible for their
historical consumers; ordinary reuse no longer depends on a short-lived binding
recovery grant. Unknown same-generation window creation still retains its sole
correlated observer and never resends that creation.

## Public paths and file custody

The normal `browser_*` path uses Camofox at `camofox.eyrie`. The persistent
`secure_browser_*` path uses the authenticated TLS endpoint at `browser.eyrie`,
its resident controller, and the same Firefox/profile Joy sees on the desktop.
Both support ordinary navigation, snapshots, screenshots and interaction.
Persistent Firefox additionally preserves the owner's authenticated session and
uses distinct internally coordinated windows rather than ephemeral sessions.

The old persistent surface had no exact-byte file retrieval operation. The new
`secure_browser_download(selector)` reads one rendered HTTP(S) or blob download
link through Firefox's own GET/fetch and normal same-origin/CORS rules. It never
accepts local paths, reads profile files, exports cookies or accepts caller
JavaScript. The bounded stream is cancelled above 1 MiB or after seven seconds.
The adapter verifies size and SHA256 before saving a private local artifact;
responses contain its path and checksum, not binary data or authenticated URLs.
This is bounded browser link retrieval, not a general download-manager API;
links requiring native chrome or files above the limit remain explicit gaps.

## Executed source qualification

The reusable-window regression failed before the implementation for explicit
release, idle expiry and controller restart after release. The updated browser
fixtures and adapter checks pass. New regressions are included in the existing
required window-fixture CI lane; `.gitlab-ci.yml` is already unmanaged in
`.sync.yml`.

The real public-schema/handler → verified TLS → endpoint → resident controller
→ Firefox journey ran in a network-disabled disposable copy of the installed
image, with no owner mounts. It exercised navigation, snapshots, screenshot,
coordinate/selector clicks, typing, scrolling, independent effect counts after
lost native and HTTP acknowledgements, release/reuse without explicit acquire,
exact 262144-byte download custody, observer reconstruction, concurrent workers
in distinct windows, actual 60-second idle expiry through the endpoint janitor,
and a disposable Firefox SIGKILL followed by ordinary launcher restart and
successful browsing. Unknown action records remained byte-equivalent throughout.
Deliberate terminal cleanup verified exact native absence and refused later
allocation. The initial expanded-canary attempt incorrectly expected cleanup to
remain pending after the real endpoint janitor had already closed the window;
that failed test expectation is retained separately from the corrected pass.

These are source qualification results, not an installed production acceptance
claim. Reviewed source, exact-head CI, managed delivery, installed source parity
and recovery of the original ^2386 consumer remain separate required gates.
No production Firefox restart or uncertain-action retirement was performed.

## Concurrent original-owner continuation and delivery preparation

While this repair was being prepared, trusted steering on ^2386 recorded Joy's
newly supplied original GPX and explicitly resumed that application independently
of browser repair. Its owner subsequently completed the original request. The
durable owner-supplied file verifies as 38962 bytes, SHA256
`0a79a85a5b896fcf5dd03fe2653ee5212fa3907c45ced2d5f66c29be74a5a3e4`.
That is genuine original-byte custody, but not browser retrieval or evidence that
this repair restored its old browser scope. Do not reopen the now-terminal
request, modify its history or substitute another identity as proof of recovery.
The later legitimate terminal receipt must remain fenced.

The source repair merged through !775 after exact-head pipeline 13574. Final
native qualification exposed an omitted known-error code in the endpoint's
allowlist; the additive correction at source
`517e4c131967cdcd58341bd17752297aa274f152` preserves the actual
`FIREFOX_SCOPE_TERMINAL` / `not_started` outcome. The containing local run passes
292 tests and 25 subtests; the real public workflow passes the explicit refusal
assertion as well as the preceding browser journeys.

The rebuilt managed image is
`registry.gitlab.joyfullee.me/nest/tools/firefox@sha256:0d922fdcc68ac020fc4ba728971b85bb195207f98f68aad347a32cd57de72199`.
Authenticated remote manifest verification and pull-back succeeded, and all eight
extracted controller assets match source. Initial publication authentication
failures were diagnosed and retained; the final publication uses the existing
Talon identity through a temporary private authfile, removed afterward.

Changing the KubeCM image and image_revision changes the singleton Recreate pod
template. It is a browser restart, not a controller-only operation. Keep that
image-pin merge/deployment gated on the exact disclosed interruption scope.
The existing controller-refresh path can install these verified extracted assets
without restarting Firefox; the separately tagged Puppet bridge update can
install the adapter without a runtime-pin change. Neither operation establishes
persistent-image activation or permits erasing historical uncertain actions.
