# Camofox browser surfaces

This is the source-managed Nest implementation for the first Camofox browser
runtime surfaces. It intentionally runs side by side with the existing
Chrome/Kasm `secure-browser` workload; it does not cut production browser or
secure-browser clients over to Camofox.

## Source-managed image

The image recipe lives in this repository, using the existing Nest tool-image
pattern:

- `manifests/tool/camofox.pp`
- `data/build/Gentoo/camofox/camofox.yaml`
- `plans/build/camofox.pp`
- `bin/build camofox zen5 ...`

It builds `registry.gitlab.joyfullee.me/nest/tools/camofox:latest` from the
standard `nest/stage1/server:zen5` path. The Puppet class installs the pinned
`@askjo/camofox-browser` package and its Camoufox runtime during image build so
pods do not fetch browser binaries at startup. The image remains authority-free:
no cookies, profile state, kubeconfigs, SSH keys, tokens, or Joy browser data are
baked into it. The image does pre-fetch the public Bitwarden Firefox XPI into
`/opt/nest/camofox/extensions/bitwarden.xpi` so the secure instance can enable a
managed extension policy without embedding Joy's vault state or browser profile
into the image.

The matching external `nest/tools/camofox` GitLab project should be created with
the same small CI-wrapper shape as the other `nest/tools/*` repositories before a
registry pipeline is considered production-ready. The build implementation
itself is in this Nest config repository.

## KubeCM app model

The Kubernetes side is one KubeCM app named `camofox` with multiple service
instances:

- `camofox-general` (`service_instance: general`)
- `camofox-secure` (`service_instance: secure`)

Relevant files:

- `data/kubernetes/app/camofox.yaml`
- `data/kubernetes/service/camofox-general.yaml`
- `data/kubernetes/service/camofox-secure.yaml`
- `plans/eyrie/ai/deploy_camofox.yaml`
- `plans/eyrie/ai/deploy_camofox_general.yaml`
- `plans/eyrie/ai/deploy_camofox_secure.yaml`

The general instance is deliberately not called "Hermes browser" even though
Hermes browser tools are the likely first client. It is intended to be the
ordinary, low-authority automation surface, so its `/home/node/.camofox` profile
is backed by `emptyDir` and should be treated as disposable across pod
replacements.

The secure instance is a canary/runtime surface for the secure-browser
migration, not the live shopping/final-purchase path. It keeps a persistent
`/home/node/.camofox` PVC so Joy-operated login/session continuity can survive
pod replacement, and it carries the Bitwarden Firefox extension preinstall
intent separately from any active final-purchase authority.

The top-level `nest::eyrie::ai::deploy` plan has a `camofox` switch defaulting to
`false`. This keeps normal AI deploys from silently introducing the new browser
surface before review. To render without applying:

```sh
bolt plan run nest::eyrie::ai::deploy_camofox_general deploy=true render_to=/modules/nest/build/camofox-general.yaml
bolt plan run nest::eyrie::ai::deploy_camofox_secure deploy=true render_to=/modules/nest/build/camofox-secure.yaml
```

The `render_to` path keeps this in Helm-template/render mode; it does not apply
resources to the cluster.

## Rollout knobs

`data/host/owl.yaml` exposes non-cutover environment hints for Talon and Star:

- `CAMOFOX_GENERAL_URL=https://camofox-general.eyrie`
- `CAMOFOX_SECURE_URL=https://camofox-secure.eyrie`
- `SECURE_BROWSER_CAMOFOX_URL=https://camofox-secure.eyrie` for Star

It intentionally does not set the active Hermes `CAMOFOX_URL`. A future canary
can opt a profile into the general Camofox backend explicitly after the KubeCM
service is healthy and Joy approves the follow-through.

## Security and feature tradeoffs

The secure Camofox service does not weaken the final purchase gate. Any final
purchase remains blocked unless the existing secure-browser flow performs:

1. owner-only checkout review sent directly to Joy
2. material summary binding
3. trusted Agent Request approval
4. live re-read/revalidation
5. exactly-one final control action
6. post-purchase proof handling without exposing secrets

For non-final-purchase behavior, the implementation should meet Camofox at its
real API level instead of forcing Chrome/CDP parity. Expected changes include
using REST snapshots, stable refs, screenshots, structured extraction, and a
future backend adapter for secure-browser tools rather than raw CDP shims. Console
collection and Chrome-specific policy behavior are not assumed to exist.

## Validation checklist

Source checks:

- `pdk validate`
- `ruby -e "require 'yaml'; Dir['data/**/*.yaml'].each { |p| YAML.load_file(p) }"`
- `./bin/build camofox zen5 build=false deploy=false` for plan wiring when a
  build host is available

Render checks:

- render `deploy_camofox_general` with `deploy=false`
- render `deploy_camofox_secure` with `deploy=false`
- confirm `camofox-general` renders with an `emptyDir` profile and no durable
  browser-session PVC
- confirm `camofox-secure` renders with a profile PVC, the Bitwarden policy
  ConfigMap, a distinct Deployment, Certificate, Service, and HTTPProxy
- confirm no resources mutate the current `secure-browser` Chrome/Kasm workload

Canary checks after image publication and review approval:

- deploy only `camofox-general` first
- verify `/health` through the private Eyrie endpoint
- create/navigate/snapshot/click/type/screenshot through Camofox Browser's REST
  API
- restart the general pod and verify its profile behaves as disposable state
- only then test `camofox-secure`; verify profile persistence and Bitwarden
  extension availability, while keeping Star's active
  `SECURE_BROWSER_CDP_URL` pointed at the existing Chrome/Kasm service until the
  secure-browser backend adapter is separately reviewed
