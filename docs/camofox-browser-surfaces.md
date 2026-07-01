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

It normally builds `registry.gitlab.joyfullee.me/nest/tools/camofox:latest` from
the standard `nest/stage1/server:zen5` path. In this context, "refresh" is the
existing Nest tool-image `refresh => true` build mode in `nest::build::tool`: the
build container is created from the previously published
`registry.gitlab.joyfullee.me/nest/tools/camofox:latest` image instead of the
stage1 base, then Puppet reapplies `nest::tool::camofox`, the smoke check runs,
and the container is committed/pushed back to the same tool-image tag if deploy is
approved. It is not a live Kubernetes pod restart and it does not mutate the
running Camofox services until a later approved image publish/deploy step. The
Puppet class installs the pinned `camofox-browser` package and its Camoufox
runtime during image build so pods do not fetch browser binaries at startup. Those
refreshed builds explicitly remove the legacy scoped `@askjo/camofox-browser`
package first, because both packages expose the same `camofox-browser` executable
and stale refreshed images can otherwise keep serving the old scoped runtime. The
image remains authority-free: no cookies, profile state, kubeconfigs, SSH keys,
tokens, or Joy browser data are baked into it. The image does pre-fetch the public
Bitwarden Firefox XPI into `/opt/nest/camofox/extensions/bitwarden.xpi` so the
secure instance can enable a managed extension policy without embedding Joy's
vault state or browser profile into the image.

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

The public root of each Camofox operator host is now the persistent
KasmVNC-backed browser surface. `https://camofox.eyrie/` is the stable general
operator URL, and `https://browser.eyrie/` is the secure operator URL Joy is
most likely to use for password/login work. Both should load KasmVNC's web
client rather than REST JSON. Camofox Browser's REST API is kept on `/api/` below each operator host,
rewritten back to the Camofox REST root. The old `camofox-general.eyrie` and
`camofox-secure.eyrie` operator hostnames and the temporary
`camofox-general-api.eyrie` / `camofox-secure-api.eyrie` API hostnames are not
retained as compatibility aliases.

The deployment runs a `kasmweb/firefox` single-application KasmVNC container
beside the Camofox Browser container in the same pod. KasmVNC owns the visible X
display and web UI, with Basic Auth disabled behind the private Eyrie ingress
just like the existing Chrome/Kasm secure-browser surface. Using Kasm's
single-application browser image avoids the general Ubuntu desktop, panels, and
icons; Joy lands in a browser-only surface rather than a full desktop. The
Camofox container waits for the shared X socket, then starts with
`CAMOFOX_HEADLESS=false`, `DISPLAY=:1`, and `XAUTHORITY` pointed at the Kasm
user's authority file. Operator-visible Camofox contexts therefore render in the
persistent KasmVNC browser workspace instead of calling upstream `toggle-display`
to spawn a short-lived fixed `Xvfb :99` plus x11vnc helper.

KasmVNC is deliberately the viewport owner because its normal web client supports
remote/client resizing (`desktop.allow_resize: true` in KasmVNC's documented
defaults). Validation should prove this from the live surface: changing a desktop
or mobile browser viewport must change the remote display/browser geometry, not
only CSS-scale a fixed 1920x1080 framebuffer.

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

`data/host/owl.yaml` exposes non-cutover environment hints for Talon and Star.
REST clients should use the canonical `/api` paths; humans/operators should use
the operator host roots:

- `CAMOFOX_GENERAL_URL=https://camofox.eyrie/api`
- `CAMOFOX_GENERAL_OPERATOR_URL=https://camofox.eyrie`
- `CAMOFOX_SECURE_URL=https://browser.eyrie/api`
- `CAMOFOX_SECURE_OPERATOR_URL=https://browser.eyrie`
- `SECURE_BROWSER_CAMOFOX_URL=https://browser.eyrie/api` for Star

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
- confirm the rendered Certificate covers only the canonical operator hostname
- confirm the operator HTTPProxy routes `/` to KasmVNC port 6901 and `/api` to
  the REST API port 9377 with a prefix rewrite
- confirm no companion `*-api.eyrie` HTTPProxy or DNS alias is rendered
- confirm no resources mutate the current `secure-browser` Chrome/Kasm workload

Canary checks after image publication and review approval:

- deploy only `camofox-general` first
- verify `https://camofox.eyrie/` loads the KasmVNC operator client, not
  JSON
- verify `https://camofox.eyrie/api/health` and
  `https://browser.eyrie/api/health` return Camofox Browser JSON
- create/navigate/snapshot/click/type/screenshot through Camofox Browser's REST
  API
- create an operator-visible Camofox context and verify it appears in the
  persistent KasmVNC display without calling `toggle-display`
- resize a desktop client and a mobile-sized client and verify the remote display
  geometry changes instead of shrinking/scaling a fixed framebuffer
- restart the general pod and verify its profile behaves as disposable state
- only then test `camofox-secure`; verify profile persistence and Bitwarden
  extension availability, while keeping Star's active
  `SECURE_BROWSER_CDP_URL` pointed at the existing Chrome/Kasm service until the
  secure-browser backend adapter is separately reviewed
