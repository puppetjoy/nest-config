# Camofox browser surfaces

This page records the current Nest split between the ordinary Camofox browser
API and the persistent secure browser.

- `camofox.eyrie` is the singleton low-authority Camofox/Camoufox REST browser
  API for ordinary Hermes browser tooling. Its public root may expose the
  operator/KasmVNC surface for troubleshooting, but callers should use
  `https://camofox.eyrie/api` for the REST API.
- `browser.eyrie` is not a Camofox service. It belongs to the separate
  Firefox/Kasm secure-browser canary described in
  `docs/firefox-secure-browser-bridge.md`.
- The legacy `camofox-secure` service data is retained only as an explicit
  rollback canary and is disabled by default in `deploy_camofox`; it must not
  be used as the public secure-browser hostname or final-purchase backend
  without a new review.

## Source-managed Camofox image

The image recipe lives in this repository, using the existing Nest tool-image
pattern:

- `manifests/tool/camofox.pp`
- `data/build/Gentoo/camofox/camofox.yaml`
- `plans/build/camofox.pp`
- `bin/build camofox zen5 ...`

It normally builds `registry.gitlab.joyfullee.me/nest/tools/camofox:latest` from
the standard `nest/stage1/server:zen5` path. The image remains authority-free:
no cookies, profile state, kubeconfigs, SSH keys, tokens, or Joy browser data
are baked into it. The image may pre-fetch public browser extension artifacts as
build inputs, but extension state and Joy profile data belong to runtime PVCs or
operator-owned browser state, not the image.

## KubeCM app model

The Kubernetes side is one KubeCM app named `camofox` with a default general
service instance:

- `data/kubernetes/app/camofox.yaml`
- `data/kubernetes/service/camofox-general.yaml`
- `plans/eyrie/ai/deploy_camofox.yaml`
- `plans/eyrie/ai/deploy_camofox_general.yaml`

`camofox-general` is deliberately not named "Hermes browser" even though Hermes
browser tools are the likely first client. It is intended to be the ordinary,
low-authority automation surface, so its `/home/node/.camofox` profile is backed
by `emptyDir` and should be treated as disposable across pod replacements.

The deployment runs a `kasmweb/core-ubuntu-jammy` KasmVNC container beside the
Camofox Browser container in the same pod. KasmVNC owns the visible X display and
web UI, while Camofox serves its REST API below `/api/` on the same host. The
sidecar remains a display shell, not Joy's persistent secure browser.

## Rollout knobs

`data/host/owl.yaml` exposes the Camofox general URL hints for Talon and Star:

- `CAMOFOX_GENERAL_URL=https://camofox.eyrie/api`
- `CAMOFOX_GENERAL_OPERATOR_URL=https://camofox.eyrie`

It intentionally does not set the active Hermes `CAMOFOX_URL`. A future canary
can opt a profile into the general Camofox backend explicitly after the KubeCM
service is healthy and Joy approves the follow-through.

## Secure-browser boundary

Camofox does not weaken the secure-browser final purchase gate. Any final
purchase remains blocked unless the existing secure-browser flow performs:

1. owner-only checkout review sent directly to Joy
2. material summary binding
3. trusted Agent Request approval
4. live re-read/revalidation
5. exactly-one final control action
6. post-purchase proof handling without exposing secrets

The persistent Joy-observed browser surface is the separate Firefox/Kasm app at
`browser.eyrie`. Do not add a Camofox REST API, raw CDP/WebDriver endpoint,
credential endpoint, or final-purchase authority to that hostname.

## Validation checklist

Source checks:

- `pdk validate`
- `ruby -e "require 'yaml'; Dir['data/**/*.yaml'].each { |p| YAML.load_file(p) }"`
- `bolt plan run nest::eyrie::ai::deploy_camofox_general deploy=false render_to=/modules/nest/build/camofox-general.yaml`

Render checks:

- confirm `camofox-general` renders with an `emptyDir` profile and no durable
  browser-session PVC
- confirm `https://camofox.eyrie/api` routes to the Camofox REST API
- confirm no `browser.eyrie` Camofox route or `browser.eyrie/api` Camofox API is
  rendered
- confirm no resources mutate the rollback Chrome/Kasm `secure-browser` workload
  unless that plan is intentionally deployed
