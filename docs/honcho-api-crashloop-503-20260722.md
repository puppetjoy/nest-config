# Honcho API CrashLoop/HTTP 503 incident — 2026-07-22

## Scope

Self-hosted Honcho in the Eyrie `ai` namespace briefly failed through the user-facing `https://honcho.eyrie/health` endpoint and Hermes native Honcho integration. Evidence is sanitized: no secrets, message contents, raw memory excerpts, or credential values are included.

## Findings

- Initial symptom: `honcho-api` entered CrashLoopBackOff and the public Honcho health endpoint returned HTTP 503.
- API previous logs showed startup failure while connecting to Postgres service `honcho-cnpg-rw` / `10.102.16.7:5432` with `psycopg.OperationalError: connection refused`.
- Deriver previous logs showed the same transient database connection refusal during embedding schema validation.
- `honcho-cnpg-1` logs showed interrupted database recovery, WAL redo, checkpoint, and then `database system is ready to accept connections`.
- Node events on `owl` showed multiple `SystemOOM` warnings at the same time window, with victims including `postgres` plus adjacent browser/API/python/node processes.
- CNPG recovered automatically and now reports `Cluster in healthy state`, `READY=1`, primary `honcho-cnpg-1`, and `ContinuousArchiving=True` / `ContinuousArchivingSuccess`.
- Honcho API, deriver, Redis, embeddings, and `llama-qwen-honcho` deployments now report `1/1` available.
- `https://honcho.eyrie/health` now returns HTTP 200.
- `hermes --profile talon honcho status` now exits `0` and reports OK with the configured local/self-hosted base, workspace `hermes`, user peer `joy`, and AI peer `talon`.
- Hermes-native Honcho tool probes for profile/card/context/search returned successfully during verification. Their raw output was intentionally not copied into this evidence report.
- Aggregate-only database probe returned `db_ok=1`, `queue_pending=10`, and `active_work_units=0`.
- Honcho backup CronJob and recent Honcho backup Jobs are healthy/completed. Adjacent Talon/Star/Beryl backup Jobs show failures in the namespace but were not part of the Honcho API outage.

## Root cause

The active evidence points to a host-level `SystemOOM` event on compute node `owl` that killed CNPG/Postgres and multiple dependent application processes. When API and deriver restarted while CNPG/Postgres was still recovering, their startup paths attempted to validate/provision against Postgres and exited on connection refusal, producing CrashLoopBackOff and public HTTP 503 until Kubernetes backoff and CNPG recovery lined up.

This was not an upstream Honcho Cloud outage. The affected path was Joy's self-hosted Honcho deployment at `honcho.eyrie`.

## Live restoration performed

No ad-hoc live mutation was required. Kubernetes/CNPG recovered the live stack automatically after the OOM window. I verified live recovery through Kubernetes rollout status, CNPG status, the public health endpoint, Hermes CLI status, native Honcho tools, and an aggregate-only database probe.

## Source-managed hardening prepared

`data/kubernetes/app/honcho.yaml` now wraps the API and deriver startup commands with a per-container-restart TCP dependency wait for:

- Postgres: `%{nest::kubernetes::service}-cnpg-rw:5432`
- Redis: `%{nest::kubernetes::service}-redis:6379`

This is deliberately implemented in the main container command rather than an init container because the incident happened inside existing pod generations: a node/system OOM killed containers, and Kubernetes restarted those containers without recreating the pod, so init containers would not rerun.

The wait does not hide a real outage permanently; it waits up to 180 seconds and then fails the container if dependencies remain unreachable.

## Validation

- `pdk validate` exited `0`.
- A render-only Bolt attempt was tried from the task worktree with:
  `bolt plan run nest::eyrie::ai::deploy_honcho deploy=false render_to=/tmp/honcho-render-t_57e414c0`
  It failed before rendering because this worktree lacks installed Bolt module dependencies: `Could not find a plan named 'kubecm::deploy'` from `plans/kubernetes/deploy.pp:64`. The worktree diagnostics showed no local `modules/` directory.
- Live recheck after the source edit still shows Honcho healthy; the source edit has not been deployed.

## Review / follow-through

The live service is restored. The prepared source change should be reviewed, then deployed through the normal Nest/KubeCM/Puppet path if accepted. After deployment, verify the rendered commands in the live API/deriver deployments and re-run the same health/status/native-tool checks.
