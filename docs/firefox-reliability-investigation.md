# Persistent Firefox reliability investigation (historical)

The [complete October 2026 incident record](https://gitlab.joyfullee.me/nest/config/-/blob/d1193ea72ad182a10dfe19425e86f962ff3eab9f/docs/firefox-reliability-investigation.md)
preserves the timeline, reproduced defects, open hypotheses, test evidence,
and distinction between source verification and installed acceptance. The
final tracked source repair, [Nest !332](https://gitlab.joyfullee.me/nest/config/-/merge_requests/332),
merged. The old rollout and soak instructions are not current operating
procedures or permission to repeat repairs.

For current workflow guidance, see [reusable Firefox request windows](firefox-reusable-browser-lifecycle.md).
Keep this persistent Firefox workload separate from Camofox. Preserve the
owner profile, authentication, journals and active work; do not replay
uncertain actions or reuse historical maintenance approvals. Treat any new
symptom as a new observation, not as proof that a historical cause recurred.
