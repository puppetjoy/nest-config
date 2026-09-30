# General secure-browser hardening

## Scope and reproduced defects

This change is site-independent. Nine generic regressions were run failing
before their corresponding fixes, and now pass:

- Ordinary typing dropped the supplied action key and coordinate at the Hermes
  adapter boundary, although the UI bridge already implemented keyed typing.
- Duplicate AX tab titles were treated as unique when a strip locator matched;
  multiple selected AX tabs were silently reduced to the first match.
- An uncertain workflow binding had no explicit non-destructive recovery action.
- Native selector lookup used the snapshot taken before canonical-tab selection.
- Link `href` observations were rejected altogether.
- Failed native URL mapping left the driver on the last scanned window handle.
- The bridge accepted unjournaled ordinary typing.
- Native typing rejected inherited editable controls because it tested the literal
  `[contenteditable=true]` attribute rather than `isContentEditable`.
- The workflow input gate accepted multiple selected AX tabs even after the
  selected-tab helper was hardened; input now requires unique selected state.

The editable guard is exercised as generated JavaScript against an unrelated
synthetic element. Existing stale-element, overlay, cross-site and uncertain
replay fixtures remain unchanged in intent. No site-specific submission detector
was added: delivered input still does not prove that a page action completed.

## Contracts

Every typing path requires an action key. Reuse the same key after transport
uncertainty: a reserved journal entry blocks input replay, whether the original
input completed or not. Keys are bound to workflow and operation, not text; do
not reuse a key for a different intended action. Text is not stored in journals.
The adapter also accepts the existing `idempotency_key` alias and forwards
coordinates. Direct bridge callers must now supply an action key too.

Tab lifecycle `recover` removes only a workflow binding. It does not select,
close, adopt or navigate any tab and does not erase action keys. Follow with an
explicit `acquire` to obtain a blank handoff tab. Never use recovery or a new key
as a way to replay uncertain input. Duplicate titles and ambiguous selection
remain fail-closed. Failed native mapping restores its initial native handle;
restoration errors propagate rather than permitting input.

Generated `document.querySelector("a").href` and collection reads return only
HTTP(S) origins. Non-links return null; non-HTTP(S) and userinfo URLs are
redacted. All path, query and fragment components are omitted, including ordinary
image paths: arbitrary path segments can carry credentials and cannot safely be
classified using parameter-name heuristics. This is origin observation, not an
export of a usable full destination URL. Collections remain capped at 120.
No arbitrary JavaScript, cookies, storage or credentials are made available.

## Verification

Run the generic regression script with Python and Node installed:

    PYTHONDONTWRITEBYTECODE=1 python3 spec/app/hermes/test_secure_browser_general_hardening.py

The RSpec wrapper `spec/files/secure_browser_general_hardening_spec.rb` runs these
regressions in the normal unit-test CI lane. Existing relevant script suites:

    SECURE_BROWSER_CONTROL_MODE=firefox-ui-v1 python3 spec/app/hermes/test_secure_browser_firefox_ui.py
    python3 spec/app/hermes/test_firefox_ui_bridge.py
    python3 spec/app/hermes/test_secure_browser_bidi_ui.py

A direct function-level run of all four modules passed 62 tests. `pdk validate`
passed including the RSpec wrapper. Two focused PDK test attempts were blocked
in spec_prep by GitLab HTTP 503/500 while cloning fixtures, not by a test
assertion. Pipeline 9534 passed Validate and Unit Test for the initial source
commit b861ba156a2d58cd64e29f2aa4fcf485f23a211f. The final follow-up commit must
receive its own exact-head CI, and live verification is still required.

## Runtime follow-through and rollback gates

The Hermes adapter and BiDi helper are Puppet-managed on owl. The UI bridge is
baked into the Firefox image by `nest::tool::firefox`; the current deployment has
no script/config volume at `/opt/nest/firefox/bin`. The existing Firefox deploy
wrapper uses a Recreate strategy. Do not restart this owner-shared browser or
substitute live-only copy operations to finish this task without an approved
non-disruptive path or Joy's explicit restart decision.

An initial Bolt preflight failed because the new worktree lacked
ruby_task_helper. `bolt module install` fixed the local project prerequisites;
then inventory-backed `bolt command run 'id -un && hostname -f' --targets owl
--stream` succeeded as joy on owl. No direct SSH fallback was used.

Before accepted follow-through, record the exact source SHA, pipeline/job IDs,
image digest and hashes of the three deployed Python files. Check browser PID
and pod UID before and after, exercise only isolated fixture pages, and verify
source/runtime parity without exporting owner tab names or URLs. Do not claim
that unit fixtures are a live browser canary.

Rollback is a source revert followed by the same approved Bolt/image deployment
path. Preserve profile PVC, tab bindings and action journals; never erase
journals to make a rollback or retry appear successful. Browser-process or
image rollback has the same owner-disruption gate as deployment.

## Remaining limitations

AX bindings still depend on unique title/locator observations, not durable
Firefox session tab IDs. Native mapping still requires a unique sanitized URL;
same-path contexts with different private queries intentionally fail closed.
Automatic title changes outside a delivered action can require explicit binding
recovery. This change does not assert complete durable identity across restart,
reorder or indistinguishable tab replacement. A broader durable native identity
redesign needs live isolated multi-tab verification before adoption.
