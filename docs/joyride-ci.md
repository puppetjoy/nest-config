# Joyride CI on Owl's ordinary runner service

Joyride application source and jobs live in `joy/joyride` (project 83).
Nest manages only the host runner instance and encrypted registration credential.
`nest::service::gitlab_runner::instances.joyride` uses the existing shared
`container-gitlab-runner` manager and rootful Podman executor. The project-scoped
runner identity is 127, locked to project 83 with tag `joyride-ci` and untagged
jobs disabled. Instance/group runners remain disabled for this application.

The instance sets `limit: 2`, `podman: true`, `qemu: true`, `bolt: false` and
`puppetcore: false`. No extra devices, capabilities or security options are
needed by current check, dual-architecture build/publish, PostgreSQL smoke and
manual TEST preview jobs. The host-scoped `nest::joyride_runner_token` is selected
through `registration_token_key`; token values must never appear in logs or
file diffs. Runners 125 and 126 retain their existing Nest configuration.

## Trust model

Jobs receive the host-root Podman API socket and QEMU binaries. A read-only
socket bind is NOT a read-only API: trusted application CI can control the host
engine, launch privileged workloads or mount host paths. This is not hostile-code,
VM or secret isolation. GitLab project permissions and trusted job authors are
therefore part of the ordinary runner trust model.

The instance does not directly inject eyaml, Bolt, Puppetcore/Forge credentials,
SSH keys or kubeconfig into jobs. The application canary verifies injected mount,
credential-file and environment hygiene plus native engine execution; it does not
probe administrative host paths through the API or claim those paths are denied.
GitLab's ordinary project job/registry credentials and narrow TEST delivery
capability remain intentional. No new credential broker or execution framework
is required.

## Routine app delivery

For backend changes, the app MR runs its own checks. After merge, the
`joy/joyride` main pipeline builds and smoke-tests the image. Use its optional
manual `preview` job to request deployment of that build's exact digest to
TEST. A successful submission is not a deployed release: check the terminal
deployment receipt and TEST readiness and running image. This path does not
require a Nest Config MR or give the app pipeline production authority.

Production is deliberately separate. After the TEST checks and a deliberate
production selection, use the existing Nest-managed production deployment. The
current consumer still selects a source-managed app digest; do not overwrite it
with a TEST label or allow the TEST credential into production. App image
selection does not publish frontend content, promote a map or release record,
change production Stripe configuration, or move production data. Use the app's
separate supported content commands for deliberate content promotion.

## Historical runner cutover and verification

1. Merge reviewed source with exact-head required CI. Deploy Puppet code using
   `bolt plan run nest::puppet::deploy backend=kubernetes`.
2. The existing registration helper reconciles the entire shared manager when
   registration scripts change. Pause admission on its existing registrations,
   record previous pause states, and let current jobs finish. Do not kill builds
   or reset the manager while jobs are running. Pause/drain runner 127 as well.
3. Stop the drained obsolete manager before activating the ordinary instance;
   reuse the existing authentication identity, never delete runner 127 itself.
   Apply with inventory-backed `nest::puppet::run` and verify the shared manager's
   registrations and exact mounts/environment names without displaying tokens.
4. Restore previous admission states promptly. Verify check, both architecture
   images and registry manifest digest, PostgreSQL smoke and terminal TEST preview
   on runner 127 under the shared manager's system identity. Verify served TEST
   source/image/result, not just a successful deploy-job HTTP submission.
5. After successful acceptance, remove the obsolete stopped manager container,
   engine/unit/drop-ins, account/group, home/storage/runtime/socket and subordinate
   mappings. Remove the obsolete private credential scope only after confirming
   no remaining consumer; preserve the host-scoped credential for runner 127.
6. Verify installed absence and managed convergence. Keep ordinary Podman, QEMU,
   shared runner state, the operator's existing subordinate range and application
   data/PVCs, artifacts and rollback images. None is dedicated obsolete scaffolding.

Source deletion alone does not remove installed units, accounts or storage.
One-host retirement is live operational cleanup, not a permanent Puppet migration
framework. If activation fails before acceptance, keep the drained old state for
bounded diagnosis; do not mark removal complete. After verified retirement do not
restore the special engine or public informational site as a hidden prerequisite.
The withdrawn signing/custody/supervisor system remains retired.
