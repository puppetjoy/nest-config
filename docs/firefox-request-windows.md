# Same-session Firefox request-window cutover (historical)

The [original staging and verification record](https://gitlab.joyfullee.me/nest/config/-/blob/6334b889cc3d2ee18809c3045951bf58f3b48d56/docs/firefox-request-windows.md)
preserves the cutover design, compatibility limits, and isolated test results.
The old v2 production status, candidate image pin, and staging instructions
are historical. The serving Firefox workload now selects `firefox-windows-v3`.
This readback does not retroactively establish acceptance of an old workflow.

See [reusable Firefox request windows](firefox-reusable-browser-lifecycle.md)
for current lifecycle and recovery guidance. Keep the single persistent profile,
owner windows, and action journals intact. Do not replay uncertain input or
reuse the original cutover approval for a new build, restart, or promotion.
