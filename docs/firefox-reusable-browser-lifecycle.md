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
