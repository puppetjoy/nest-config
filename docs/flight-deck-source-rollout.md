# Flight Deck source rollout

The init container fetches application source into an emptyDir and records
`/app/.flight-deck-source-revision`. A source merge does not update a running pod.
DEV follows Flight Deck `main` on `agent-requests-dev`; production stays on a
separate exact pin and uses `agent-requests`.

## DEV: rolling source

Use an ordinary MR in the Flight Deck repository. The existing validators run
in the MR and on resulting `main`; the branch pipeline is redundant once an MR
is open. Compare the serving revision with the accepted `main` before deciding
whether to refresh DEV. If only CI configuration changed, leave the healthy
pod running; do not refresh DEV or promote production just to change a SHA.

For a runtime change, record the accepted `main` SHA for verification, not as a
Nest Config pin. Use the existing DEV Bolt plan (no `source_revision`):

From the Nest project root (or an isolated Nest worktree containing the accepted
source and installed modules):

```sh
./bin/bolt-wrapper module install
./bin/bolt-wrapper plan run nest::eyrie::ai::deploy_flight_deck_dev --stream
```

An unchanged Helm template does not replace a pod. For an app-only DEV release,
use the established targeted restart of `deployment/flight-deck-dev` in namespace
`ai` if the Bolt deploy did not create a fresh pod. Never restart production for
this step. Verify the Ready DEV pod, compare the revision record to the intended
SHA, and smoke-check HTTPS and the read-only API on the DEV board. If `main`
moved, qualify the revision actually fetched before using it for promotion.

## Production: deliberate promotion

After DEV verification and separate promotion approval, set
`flight_deck_source_revision` in `data/kubernetes/service/flight-deck.yaml` to
the full lowercase SHA actually verified in DEV. Use the normal Nest Config MR
and CI. Do not override the committed pin in private Hiera. Then run:

```sh
./bin/bolt-wrapper plan run nest::eyrie::ai::deploy_flight_deck_prod \
  source_revision="$ACCEPTED_SHA" --stream
```

Set `ACCEPTED_SHA` to the committed pin. The parameter verifies the pin; it
does not override it. The changed pin updates the pod template; the init container
checks out and verifies that exact commit. Check the Ready production pod,
template pin, runtime revision and production read-only API. Do not substitute a
restart for changing the production pin. Roll back by restoring the previous
verified pin and deploying through the same production plan.

For render-only checks, use `render_to` with a private, mounted project `build/`
path and verify a nonempty host-visible manifest. `deploy=false` checks the
arguments and configured pin without rendering or upgrading Helm.
