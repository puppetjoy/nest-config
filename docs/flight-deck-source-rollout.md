# Exact-source Flight Deck rollout

Flight Deck's init container fetches application source into an emptyDir. A
source-only upstream commit cannot update an already-running pod. Set
`flight_deck_source_revision` in the instance's public service data to a full,
lowercase 40-hex commit SHA. The deployment and pod-template annotations and init
container environment all use that pin, so changing desired source triggers a
normal Helm-managed rollout. The init container fetches that exact commit,
checks it out detached, verifies HEAD equality, and records
`/app/.flight-deck-source-revision`. Failed fetches or malformed pins fail closed.
An empty pin retains the existing repository/ref clone behavior.

The existing Dev, Prod and shared YAML deploy plans expose `source_revision` as
an optional expected-revision guard. It must match the committed instance pin;
it is deliberately not an ephemeral Hiera override. Update service data through
the normal MR/CI workflow before deploying a new revision. Keep these public
service pins authoritative; do not override them in private Hiera.

From the Nest project root (or an isolated Nest worktree containing the accepted
source and installed modules):

```sh
./bin/bolt-wrapper module install
./bin/bolt-wrapper plan run nest::eyrie::ai::deploy_flight_deck_dev \
  source_revision=885ca9f9f1946f0555802a304444588db2349b9d --stream
```

For a render-only check, add
`render_to=/modules/nest/build/flight-deck-dev-ai/source-check.yaml`. The host
TMPDIR is not necessarily visible to inventory localhost inside the Bolt
container; use the mounted project path. `deploy=false` checks plan arguments
and desired pin without rendering or upgrading Helm.

Read back the deployment template pin, ready pod, actual Git HEAD, revision
record and the user-facing API. Do not use pod patches or manual rollout
restarts as a substitute. Promote the same accepted source to production service
data only after DEV validation; then run `deploy_flight_deck_prod` with its
matching expected revision and repeat installed-source/API verification.

For requests 1859/1860, live internal_test fixtures, browser acceptance and the
secondary-worker freshness follow-through remain with the canonical Flight
Deck task. This Nest prerequisite initially pins the explicitly requested
885ca9f9f1946f0555802a304444588db2349b9d in DEV only; it does not promote an
unverified follow-up SHA or restart production.
