# Camofox browser REST API

This page records the source-managed Nest split between the ordinary Camofox
browser API and Joy's persistent secure browser.

- `camofox.eyrie` is the singleton Camofox/Camoufox REST browser API for
  ordinary Hermes browser tooling. It is agent-first and ephemeral, not a VNC or
  operator desktop.
- `browser.eyrie` is not a Camofox service. It belongs to the separate
  Firefox/Kasm secure-browser canary described in
  `docs/firefox-secure-browser-bridge.md`.
- The previous `camofox-general` and `camofox-secure` service instances,
  `/api` operator-host rewrites, KasmVNC sidecar, display sharing, and noVNC
  operator surface were historical exploration and are not part of this final
  Camofox shape.

## Source-managed Camofox image

The image recipe lives in this repository, using the existing Nest tool-image
pattern:

- `manifests/tool/camofox.pp`
- `files/nest/tool/camofox/nest-camofox-browser.sh`
- `plans/build/camofox.pp`
- `bin/build camofox zen5 ...`

It normally builds `registry.gitlab.joyfullee.me/nest/tools/camofox:latest` from
the standard `nest/stage1/server:zen5` path. The Puppet class installs the
pinned `camofox-browser` package and its Camoufox runtime during image build so
pods do not fetch browser binaries at startup. Refreshed builds explicitly
remove the legacy scoped `@askjo/camofox-browser` package first, because both
packages expose the same `camofox-browser` executable and stale refreshed images
can otherwise keep serving the old scoped runtime.

The image remains authority-free: no cookies, profile state, kubeconfigs, SSH
keys, tokens, or Joy browser data are baked into it. It includes Joy's managed
Nest font set through `nest::gui::fonts` so standard-browser screenshots render
with the same baseline fonts as the Firefox secure-browser image. It may still
carry the public Bitwarden XPI cache for future experiments, but the singleton
Camofox API does not enable a persistent secure-browser profile or final-purchase
authority.

## KubeCM app model

The Kubernetes side is one KubeCM app and one service:

- app: `camofox`
- service: `camofox`
- canonical REST URL: `https://camofox.eyrie/`

Relevant files:

- `data/kubernetes/app/camofox.yaml`
- `plans/eyrie/ai/deploy_camofox.yaml`

The Camofox pod exposes the Camofox Browser REST API directly through Contour at
`https://camofox.eyrie/`. It runs headless/default Camofox Browser behavior with
a managed 1365x768 default fingerprint screen and matching 1365x768 virtual
fallback display. The pod also carries a narrow 2.4.6 startup shim for the
current Camofox package: after fingerprint generation/load, it pins the
fingerprint sidecar's screen, window, and viewport-derived metrics back to the
configured 1365x768 desktop shape so `window`, `screen`, document width, and
viewport screenshot dimensions agree. The emptyDir `/home/node/.camofox` profile
keeps automated sessions disposable across pod replacement, which also forces
Camofox to regenerate generation-time `CAMOFOX_SCREEN_*` fingerprints after a
deploy.

## Rollout knobs

`data/host/owl.yaml` points Hermes standard browser tools at the singleton REST
API:

- `nest::app::hermes::browser_camofox_url=https://camofox.eyrie`
- `CAMOFOX_URL=https://camofox.eyrie`

Star secure-browser operations bind to the separate persistent Firefox/Kasm
`browser.eyrie` app, not to Camofox.


## Secure-browser boundary

Private-network navigation and temporary HTTPS-error ignores are enabled for this
trusted internal endpoint so Hermes can open `.eyrie` pages such as Flight Deck.
The app NetworkPolicy still blocks cloud/link-local metadata egress. Do not reuse
this no-auth/private-network combination for public or multi-tenant Camofox.

This Camofox service does not weaken the secure-browser final purchase gate. Any
final purchase remains blocked unless the existing secure-browser flow performs:

1. owner-only checkout review sent directly to Joy
2. material summary binding
3. trusted Agent Request approval
4. live re-read and revalidation
5. exactly-one final control action
6. post-purchase proof handling without exposing secrets

For standard browser tools, meet Camofox at its REST API level: navigation,
accessibility snapshots, refs, screenshots, extraction, and explicit viewport
resizing. Do not add VNC/noVNC/operator desktop shims to this app.

## Validation checklist

Source checks:

- `ruby -e "require 'yaml'; Dir['data/**/*.yaml'].each { |p| YAML.load_file(p, aliases: true) }"`
- `pdk validate`

Render checks:

- render `deploy_camofox` with `deploy=false`
- confirm the rendered Deployment has one `camofox` container and no Kasm/VNC
  sidecar, display env, operator port, or persistent profile PVC
- confirm the rendered Service exposes only port 9377
- confirm the rendered HTTPProxy routes `/` directly to the REST API service
- confirm no `camofox-general`, `camofox-secure`, or `*-api.eyrie` resources are
  rendered
- confirm no resources mutate the Firefox/Kasm secure-browser workload

Canary checks after review approval:

- deploy only the singleton `camofox` app
- verify `https://camofox.eyrie/health` returns Camofox Browser JSON
- create/navigate/snapshot/click/type/screenshot through Camofox Browser's REST
  API from Hermes browser tools
- verify desktop screenshots use a normal viewport with no right-edge crop or
  giant remote desktop framing
- verify an explicit mobile viewport/probe is intentionally mobile-sized
- restart the pod and verify its browser state is disposable
