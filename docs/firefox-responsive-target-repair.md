# Firefox responsive target selection repair

Request ^2219, task `t_3d70262f`; original workflow acceptance remains with
^2218 / `t_14d07a4a`.

## Reproduction and cause

Read-only native diagnostics, serialized under the resident endpoint lock,
reproduced the exact `ELEMENT` guard failure on GitHub's About edit button.
The selector `button[aria-label="Edit repository metadata"]` matched two
responsive-layout copies. One was rendered at 24 by 24 pixels; the other had
zero geometry because its ancestor was hidden. The guard required exactly one
raw selector match before checking visibility, so it rejected both together.
The HTTP endpoint then mislabeled that pre-input exception as
`FIREFOX_OUTCOME_UNCERTAIN`.

The installed controller hash at diagnosis was
`a261902025bd4e9c9422182ba6cbd8b48963f4b38812d473aa4db6c145364f83`.
The signed-in native generation was
`3fa376e3705e5537626247238deddfaac655fb00cd01b472`.
No diagnostic click, page modification, credential export, or journal edit was
needed to identify this cause. Historical generic errors do not prove input was
sent; this repair does not retrospectively clear any retained uncertain key.

A separate fresh-scope diagnostic hit the existing native-window budget:
12 native windows, 14 contexts and four open journal bindings. The current
request remained unallocated. Unknown windows must not be adopted or closed,
and the budget must not be silently increased to make a canary pass.

## Durable behavior

Selector cardinality now applies to rendered matches, excluding zero-size,
hidden, collapsed and display-none candidates. Multiple rendered matches still
fail closed. The existing viewport, interception, disabled/protected field,
shared native node identity, generation and scope checks remain enforced.
No DOM click or JavaScript input fallback is added.

Pre-journal element/initial-focus script rejection returns
`FIREFOX_TARGET_UNAVAILABLE` with `outcome: not_started`. A bounded direct-query
script exception returns `FIREFOX_OBSERVATION_UNAVAILABLE`; native window
budget refusal returns `FIREFOX_WINDOW_BUDGET`. The endpoint and Hermes adapter
preserve these fixed, privacy-safe codes. Transport failure and post-journal
field/readback exceptions remain uncertain. Started actions and historical
keys retain the original non-replay boundary.

## Verification

The focused resident, endpoint, creation/generation recovery, scoped admission
and controller refresh suites passed: 131 tests. The existing Node CI fixture
also executes the actual fixed `ELEMENT` source against responsive duplicates,
visible ambiguity, interception and disabled controls. A disposable native
Firefox canary, with networking disabled and no owner mounts, verified a real
responsive-duplicate click and independent changed heading, rejected two
rendered duplicates without an action journal entry, and passed existing
session, focus, typing, multiline, protected-input, screenshot, owner viewer,
observer reconnect and exact terminal-close checks.

The first disposable harness invocation omitted DISPLAY and stopped at its
focus observation. The corrected fresh disposable invocation used DISPLAY=:1
and passed. This was a harness setup error, not a production Firefox failure.

Bolt discovery from this isolated project initially reported a missing
`ruby_task_helper`. `bolt module install` resolved the project dependency;
`bolt inventory show owl --detail --format json` and the documented
`bolt command run 'id -un && hostname -f' --targets owl --stream` smoke then
succeeded as joy on owl. No direct SSH or ad-hoc host Puppet deployment was
used.

## Activation and acceptance

Use exact-head CI and the managed Firefox build, then the documented
controller-only overlay refresh through inventory-backed Bolt. Preserve the
native process/session, all owner tabs and all journals. Do not perform a
singleton Recreate rollout merely to activate these controller files.
Apply the Hermes adapter via `nest::puppet::deploy` and the tagged
`nest::puppet::run` path. Record exact merged source, CI, image and installed
hashes in the task handoff. The original parent retains GitHub description
editing and independent public API verification; neither belongs to this
repair's source change.
