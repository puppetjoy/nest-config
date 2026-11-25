# Shared Firefox protocol ownership repair (historical)

The [original incident and verification record](https://gitlab.joyfullee.me/nest/config/-/blob/c651a929db19a81341d301924f1ffb7a90ca143f/docs/firefox-session-ownership-repair.md)
preserves the adapter and image identities, reproduced ownership failure, and
then-current canary and deployment notes. Do not reuse those image pins or
replay the recovery. A new incident needs fresh installed-state evidence.

See [reusable Firefox request windows](firefox-reusable-browser-lifecycle.md)
for current lifecycle guidance. The persistent browser has one controller-owned
session; reconnecting an observer must not create or end it. Verify the managed
adapter overlay and the processes importing it separately from workload health.
Keep PatternKit's separate workbench browser outside that recovery scope.
Preserve the profile, owner tabs and action journals, and read back uncertain
outcomes before any further input. Do not replay an uncertain operation.
