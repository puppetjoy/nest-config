# Shared Firefox input verification and tab provenance repair

## Scope and limits

Agent Request ^2016, task t_d8b2ce42, independently repairs shared Firefox
platform seams reported by the original Joyride client ^1981. It does not pause
that client's application work. The original sanitized report remains at
`/home/joy/projects/.worktrees/nest-config/t_befb85e8/build/joyride-run11865/browser-defect-report.md`.
Its action keys, uncertainty and distinctions remain authoritative.

The report proves seven total tabs, not seven Muse tabs. Joy separately saw
approximately five Muse tabs. Thirteen expired workflows were records, not proof
of thirteen extant tabs. Fresh supported authenticated, TLS-verified
`browser.eyrie` status and accessibility snapshot during this repair expose one
New Tab, an empty URL and generation
`a71c8869a8fb38d9e6ba5ad1d12dd93f26f27c9fa1db9a350042713ef05be217`.
They retain uncertain old workflows. This contradicts the earlier topology but
does not establish who changed it, whether the old tabs were safely disposed,
or whether a canonical Luna chat is usable. No old tab was closed, recovered,
rebound or navigated by this repair worker. No private draft or chat content was
copied, and no uncertain typing or Send action was replayed.

The original DOM/accessibility/screenshot disagreement has not been reproduced
as a rendering failure here, and no compositor or page root cause is claimed.
Historical session exhaustion is not claimed to be a fresh live incident.
The demonstrated reporting and lifecycle defects below are narrower.

## Demonstrated source defects and repair

The initial focused regression run failed five cases: ordinary and selector
input both reported delivered without visible-field evidence; ordinary readback
failure still left a successful journal; a dropped Ctrl+W forgot ownership and
reported successful closure; and recovery discarded binding provenance.

- Typing now reserves its existing action key before input and commits delivery
  only after readback. Exact, bounded, private AT-SPI text/caret observations
  establish ordinary insertion on the same focused field and tab. Locator and
  coordinate confirmations must refer to that field. Selector input additionally
  requires expected native value, focused AX value and native active-element
  identity to agree. Raw comparison values are neither journaled nor returned.
- Missing, ambiguous, redacted, oversized, selected-text or otherwise unsupported
  observations remain `delivery_uncertain`; replay never sends input again.
  `typed_chars` is not claimed for unconfirmed input. Rich-text controls without
  exact value/selection observations can be dispatched but remain uncertain;
  their old dispatch-only tests no longer call that delivered. Readback failure
  leaves the reserved `delivery_started` journal, which also blocks replay.
  AX confirmation is not pixel OCR or proof of page submission/completion.
  New journals retain only a confirmation boolean. Historical dispatch-only
  typing journals without that evidence remain untouched and non-replayable,
  but are not reported as verified delivery or used to clear recovery uncertainty.
- Native selector mapping previously activated every handle to scan URLs and
  rejected duplicates. It now observes the selected context through the same
  WebDriver session's BiDi connection, using the existing active-window and
  isolated-document-visibility checks. BiDi context IDs and WebDriver handles
  share the W3C navigable identity. Mapping is revalidated before input. No
  caller-supplied script, URL/title ownership inference or second session.new
  is introduced. Borrowed connections close without ending the owner's session;
  the WebDriver context retains its existing bounded teardown.
- Explicit recovery can renew exact same-process canonical identity when the
  binding is certain, or its only recorded uncertainty is lease expiry, and no
  action is uncertain. It neither selects a tab nor discards a draft. Unknown
  historical uncertainty, generation changes, missing identity and uncertain
  closure cannot use this path. Other recovery preserves an abandoned-binding
  record and all journals. Known abandoned tabs remain claimed; unresolved
  provenance prevents repeated replacement-tab creation. No uncertain input is
  reclassified as successful by recovery.
- Release persists closure uncertainty before its one shortcut, then observes
  the exact expected survivor identity set and count within a bounded window.
  A dropped/ambiguous closure retains ownership and blocks another shortcut.
  Status exposes bounded provenance facts without page or draft content.

## Focused verification and image evidence

Source implementation commit:
`33446a97108d6ec4d9b71bad32999d6f5122da70` (including the historic-journal
confirmation fence after initial implementation `d4680c858fd15e22837613fd7705de930fe8709b`).

The nine focused Python suites passed 113 tests. The new stdlib-only regression
script passed all eleven tests directly and is in Secure browser fixtures CI.
`git diff --check` passed. Required exact-head CI is recorded on the MR; these
local results are not a substitute for that gate.

The enhanced isolated regression on the unchanged installed-image content
failed with the exact native selector mapping refusal, explicitly no input sent.
Two duplicate-input overlay cycles then passed. A later expanded harness attempt
failed a fixture title-readiness assertion before reaching recovery checks; that
run is retained as failed, not counted as a pass. The harness now bounds
read-only title observation rather than replaying navigation or input.

The final managed Bolt build refreshed the existing production-family image in
an isolated build container, applied the checked-out Puppet source and passed
its headless smoke test. Dedicated published tag:
`registry.gitlab.joyfullee.me/nest/tools/firefox:ar2016-input-33446a97`.
Independently pulled registry digest:
`sha256:3c295158d93aa2450e63a76eaa9be9675c16238d4a61c422b946d71e976600c1`.
Local image config identity:
`sha256:ad89463a77b1ac62993630ace9f1473e700a5d34106387aef1077f7dfde788d3`.

The final pristine image, without overlays or an owner profile, passed two
cycles and 67 public operations in 114.667 seconds, maximum operation 6.567
seconds. It verified equal-title/equal-URL native input, exact textarea
entry/replacement, protected-field redaction, idempotent replay, four explicit
recover/acquire pairs with no added replacement tabs, exact survivor count after
release, source pagination, endpoint reconnect/outage and bridge refresh.
Five survivor identities and browser generation were preserved. The disposable
browser exited gracefully and its container was absent afterward. This was a
TLS-verified localhost fixture through the shipped public adapter, with client
subprocess execution forbidden and no kubeconfig. It is not `browser.eyrie`
production acceptance, a live Luna chat test or a longevity certification.

A separate stronger coordinate-status run initially refused its fixture title
assertion because the empty profile's Bitwarden onboarding tab became selected.
It did not reach coordinate input. The returned query identified that actual
selected page rather than guessing the fixture. A bounded, opt-in initial
onboarding observation now precedes fixture workflows. On the identical final
image, the strengthened run passed 52 operations in 92.47 seconds, including
an explicit `delivered` and `visible_value_confirmed` assertion for coordinate
multiline input, with five survivor identities unchanged. This is a fixture
startup race, not proof of the original Muse rendering cause. No production
extension or profile configuration was altered. Receipt:
`coordinate-confirmation-ready-green.json`; the failed run remains retained.

Source and final-image hashes independently matched:

| Component | SHA256 |
| --- | --- |
| UI bridge | `b9ce86f8095c795df931953b62c530fc0996396332748b1a31bb4ec4cdb0038b` |
| HTTP endpoint | `cf7d733550e0438c98bd48070bef323e674e151a22a155d627ea71357be33d11` |
| Bounded BiDi reads | `75360acb63bf8af19fd52f6bcbf0cb2c11cbabd3b803610d3e3e1f6ff0d5ae70` |
| Local BiDi session helper | `b058f32129206a2c2af126973a1421dfc92eb38b99703763a061b16326c19559` |

Safe receipts live under this task's `build/browser-repair/`: original
`isolated-red.log`, passing `isolated-green.json`, `pristine-green.json` and
`final-pristine-green.json` and `journal-pristine-green.json`. The journal-fenced
receipt is the authoritative final pristine
revision. Raw build/fact logs are not user deliverables.

Registry push succeeded through the existing managed credential path. The
initial locally recorded manifest digest was not remotely pullable; a tag
readback identified the registry's compressed manifest and an exact digest pull
then succeeded. The local digest was not used as deployment evidence. A local
registry commit attempt had first failed because inherited registry credentials
caused a login to localhost, where no registry exists. Publishing used the normal
managed remote-registry plan, not a manual credential workaround.

## Historical deployment and client handoff

The [original build and retest handoff](https://gitlab.joyfullee.me/nest/config/-/blob/a6c589998d00b8d99885e73cf3092e7383acea52/docs/firefox-input-verification-repair.md#bolt-preflight-and-deployment-boundary)
retains the build commands, image pin and original-client checks. The repair
(^2016) and its original client task (^1981) are now terminal. That status does
not establish the outcome of any individual action or authorize a replay.
Preserve existing journals, unknown outcomes, and owner or unproven tabs.

For current operations see [reusable Firefox request windows](firefox-reusable-browser-lifecycle.md)
and [generation reconciliation](firefox-generation-reconciliation.md).
