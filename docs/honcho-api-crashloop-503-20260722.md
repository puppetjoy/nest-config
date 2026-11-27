# Honcho API CrashLoop/HTTP 503 incident (historical)

The [original incident record](https://gitlab.joyfullee.me/nest/config/-/blob/fa60df40a8d3d8e7db43cd6d00b7b4816b3be41b/docs/honcho-api-crashloop-503-20260722.md)
preserves the July 2026 OOM evidence, automatic recovery, and the original
qualification and deployment handoff. Its pending deployment instructions
are historical, not a current action or authorization.

The maintained [Honcho application data](../data/kubernetes/app/honcho.yaml)
defines the API and deriver startup waits for PostgreSQL and Redis. These run
on container restart, not only when a pod is created. Keep them in place.

For a new outage, check current API and deriver readiness, database state and
recent node events before attributing the failure to this incident. An HTTP 200
from `/health` verifies endpoint availability, not recall or data recovery.
Use the existing [Honcho deploy plan](../plans/eyrie/ai/deploy_honcho.yaml) only
within the approved scope; do not replay the incident handoff or a restore.
