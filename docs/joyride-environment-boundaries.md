# Joyride environment boundaries

## Current deployment

TEST (`joyride-test` in namespace `test`) and production (`joyride` in namespace
`joyride`) are separate live services. The service class accepts the exact
service, namespace and runtime-environment tuple for each. The application
Hiera default replica counts are not the effective production counts; check the
production service overrides and the installed workloads.

| | TEST | Production |
| --- | --- | --- |
| App delivery | Owning repo CI builds and previews the immutable app image through the TEST controller | Explicitly approved Nest-managed promotion of the verified artifact |
| Managed deploy plan | `nest::eyrie::deploy_joyride_test` | `nest::eyrie::deploy_joyride` |
| Readiness | `https://joyride-test.eyrie/health/ready` | `https://joyride.eyrie/health/ready` |

## Promote only the app artifact

1. Verify terminal success of the TEST preview for the exact source and immutable
   digest. Verify the installed TEST digest and check readiness. Compare the
   candidate with installed production for migrations, runtime compatibility and
   any changes to payment, mail, credentials or data access before seeking
   approval. A green readiness endpoint alone does not qualify those changes.
2. Prepare an ordinary Nest MR changing the app digest in
   `data/kubernetes/service/joyride.yaml`. Render the existing production plan
   and check the resulting diff. Draft CI is preparation; obtain explicit
   approval for the exact artifact before merging and deploying it.
   Check only the intended production resources change and that database, PVC,
   credentials, content controls and payment configuration stay production-local.
   Keep rendered manifests private. The TEST delivery API is not a production
   deployment or rollback route.
3. From the accepted Nest checkout, use the production plan. Allow the Helm
   wait to finish before imposing a client deadline. Verify a deployed Helm
   revision, the expected digest on all affected Ready workloads, production
   HTTPS readiness, and TEST continuity. To revert the app, restore the previous
   reviewed digest and use the same plan when schema compatibility permits; an
   image revert does not reverse a migration. Never restore TEST data into production.

### Reconcile an interrupted upgrade

If the client times out, do not replay Bolt. Check whether the original
operation is still running, then inspect `helm -n joyride history joyride`,
workload convergence, and both readiness endpoints. A Ready workload does not
turn a `pending-upgrade` Helm revision into a deployed release.

If the original operation has ended, the pending revision matches the approved
render, all affected workloads have converged on its digest, and the revision
has no hooks, record that same manifest as deployed with Helm's native recovery:
`helm -n joyride rollback joyride <pending-revision> --no-hooks --wait`.
Verify the new deployed revision has the same manifest and that both environments
are still healthy. Keep manifest comparisons private. If any condition fails,
diagnose it before making another change; do not use this recovery to deploy a
different image or change data, credentials, or access policy.

## Keep environment and approval boundaries

- Keep database and media storage, credentials and trusted-access paths separate.
  Do not copy TEST secrets, synthetic members, fixtures, media or controller state
  to production. The private TEST access route is not production authorization.
- An application promotion does not authorize content publication, member
  communications, payment changes, live charges or public launch. Use the
  corresponding existing paths and separate approvals. Do not trigger those
  operations as smoke tests for an application release.
- Do not revive the retired informational site or the retired signed-evidence
  admission framework. Use the existing TEST preview and managed production plan.

See [TEST delivery](joyride-test-deployment.md), [CI](joyride-ci.md),
[private TEST access](joyride-luna-private-access.md) and
[production access](joyride-production-luna-access.md). The
[historical preparation and browser-test record](https://gitlab.joyfullee.me/nest/config/-/blob/9763fcceec612104e2776f9673e84283b7c07b67/docs/joyride-environment-boundaries.md)
is preserved at its original revision. It describes the former TEST-only gate
and dormant production candidate, not current operating instructions.
