# Firefox/Kasm secure browser bridge plan

This document describes the first source-managed `browser.eyrie` secure-browser
canary and the safest path for future Hermes `secure_browser_*` tools to drive
the same visible Firefox session Joy sees.

## Current canary shape

`browser.eyrie` is modeled as a singleton KubeCM app named `firefox`:

- app data: `data/kubernetes/app/firefox.yaml`
- deploy plan: `plans/eyrie/ai/deploy_firefox.yaml`
- service marker: `manifests/service/firefox.pp`
- public operator URL: `https://browser.eyrie/`
- Nest image: `registry.gitlab.joyfullee.me/nest/tools/firefox:latest`
- build recipe: `manifests/tool/firefox.pp`, `plans/build/firefox.pp`, and
  `data/build/Gentoo/firefox/firefox.yaml`
- private automation attachment: Firefox Remote Debugging through the private
  `browser-cdp.eyrie` Contour route to Service port `9222`, consumed only by
  the guarded Hermes secure-browser tool wrappers

The app exposes a browser-accessible KasmVNC Firefox UI through a Contour
`HTTPProxy` with websocket support. It deliberately exposes no Camofox REST API,
public CDP, WebDriver, Marionette, raw VNC credentials, cookies, storage,
request headers, screenshots of secret pages, vault data, payment/address
details, or direct final-purchase authority to models.

The Nest image uses Portage Firefox via `nest::gui::firefox`, Eyrie/Nest trust
roots via `nest::base::certs`, Joy's font set via `nest::gui::fonts`, and
source-built KasmVNC from the pinned upstream `kasmtech/KasmVNC` revision. The
KasmVNC checkout and build are source-managed with `nest::lib::src_repo` and
`nest::lib::build`; native Puppet file resources install the resulting `Xvnc`
binary and built web client into `/opt/kasmweb` after the build completes.

The startup wrapper disables Firefox's Linux process sandboxes inside this
Kubernetes container because Portage Firefox's content processes otherwise
crash when user namespaces are unavailable. That is not a model/tool permission
relaxation: the browser remains isolated by the pod, NetworkPolicy, guarded
Remote Debugging attachment, and the secure-browser tool's sanitization/final
purchase gates.

State lives in a durable `firefox-profile` PVC mounted at `/home/kasm-user` so
Joy login state, Firefox profile state, and Bitwarden extension state can survive
pod replacement. The `firefox-reset-procedure` ConfigMap records the reset and
revoke flow: scale the deployment down, delete the PVC, redeploy from KubeCM,
and have Joy re-enter login/Bitwarden state directly in the visible browser UI.

Bitwarden is seeded with Firefox enterprise policy using the AMO extension id
`{446900e4-71c2-419f-a6a7-df9c091e268b}` and AMO latest-XPI URL. The policy
ConfigMap is public-extension metadata only; it does not contain Joy vault data
or credentials.

The existing Chrome/Kasm `secure-browser` workload and `secure-browser-cdp.eyrie`
remain source-managed for rollback only. When the product target is
`browser.eyrie` Firefox, Hermes secure-browser tools must bind to
`deployment/firefox`, verify the live workload is the Nest Firefox image, and
fail closed if they are pointed at `deployment/secure-browser` or
`secure-browser-cdp.eyrie`.

## Automation bridge options

### CDP

Firefox CDP support is incomplete compared with Chrome and does not match the
existing Star secure-browser implementation closely enough to make a blind
endpoint swap safe. Exposing a raw CDP-like endpoint would also make cookies,
storage, network events, screenshots, and final controls too easy to leak or
misuse.

Verdict: do not expose raw CDP from `browser.eyrie` or give profile runtimes
Kubernetes credentials just to reach it. The production bridge uses a private
Eyrie `browser-cdp.eyrie` websocket route owned by the Firefox KubeCM app and
still keeps all model-visible authority inside the guarded Hermes tool wrapper.

### WebDriver / Marionette

WebDriver and Marionette can drive Firefox reliably and can target a running
profile, but their native protocols are broad automation APIs. Direct model
access would expose too much authority: arbitrary script execution, raw DOM,
window control, screenshots, download paths, and potentially sensitive browser
state.

Verdict: usable only behind a private bridge that enforces the existing
`secure_browser_*` policy and returns sanitized results.

### Browser extension plus native helper

A signed/managed Firefox extension can observe the same visible browser session
and can be designed around high-level safe primitives. A native helper or sidecar
can hold policy, owner/session mapping, screenshot redaction, and evidence
capture without exposing browser internals directly to the model. This is the
best long-term match for preserving Joy-visible state while keeping data
boundaries explicit.

Verdict: preferred future direction when moving beyond the upstream Kasm image.
It may pair with a private sidecar for screenshot capture, health, and operator
session binding.

### Guarded Firefox Remote Debugging bridge

The first cutover keeps the public `secure_browser_*` contract in the Hermes
tool wrappers and changes their backend binding to `deployment/firefox`. The
Firefox workload enables `--remote-debugging-address=0.0.0.0` and
`--remote-debugging-port=9222`; Nest publishes that port through the private
`browser-cdp.eyrie` HTTPProxy so Star/Talon profile runtimes can attach without
`kubectl port-forward` or profile-local kubeconfigs. The tool refuses to operate
unless all requested `browser.eyrie` identity/configuration checks pass:

- configured workload is `deployment/firefox`
- live image starts with `registry.gitlab.joyfullee.me/nest/tools/firefox`
- app label identifies `firefox`
- configured workload/URL is not legacy `deployment/secure-browser` or
  `secure-browser-cdp.eyrie`

This is intentionally not a general raw-debugging API for agents; the existing
tool guardrails still own URL allowlists, query rejection, sensitive screenshot
refusal/redaction, owner-only review delivery, and final-purchase approval
gating.

### Sidecar/custom service using WebDriver internally

A sidecar can run on the private pod network, connect to Firefox through
Marionette/WebDriver or extension/native messaging, and expose only the existing
backend-neutral secure-browser contract. It can enforce operation allowlists,
checkout/final-purchase refusal, owner-only evidence routing, redaction, and
audit logging before anything reaches a model-facing Hermes tool.

Verdict: recommended first production bridge. It preserves the public
`secure_browser_*` tool contract while avoiding raw automation endpoint exposure.

### VNC-only control

Driving the browser through VNC pixels and coordinates matches what Joy sees,
but it is brittle and poor for safe structured extraction. It also makes
redaction and control attribution harder because the tool would infer state from
pixels after the fact.

Verdict: acceptable for Joy/operator manual control only, not as the primary
agent automation bridge.

## Recommended private bridge contract

Keep the public Hermes tool names and safety semantics, but route them to a
narrow private bridge/sidecar with backend-neutral primitives:

- `health`: readiness and version facts without secret state
- `owner-tab/session mapping`: stable owner-scoped visible tab selection
- `navigate`: bounded URL navigation with login/security-page pauses
- `snapshot/text/controls`: sanitized visible text and non-secret controls
- `constrained query`: read-only structured facts with mutation/network/storage
  tokens rejected
- `click/type/press`: allowlisted effects only; final purchase remains refused
  unless the existing trusted approval executor path revalidates the live page
- `screenshot/redaction input`: viewport/full-page capture only after page-class
  checks and browser-side redaction for sensitive checkout/account pages
- `owner-only evidence capture`: complete sensitive checkout/order evidence goes
  directly to Joy, never back to the model
- `audit`: durable high-level operations without cookies, DOM dumps, raw headers,
  storage, vault data, payment/address details, or raw order numbers

This bridge should be private to the cluster/profile runtime, not a public
`browser.eyrie` route. `browser.eyrie` should remain the visible Kasm UI.

## Image build and validation

The Firefox image follows the existing Nest tool-image pattern:

- `manifests/tool/firefox.pp` applies `nest::gui::firefox`, `nest::gui::fonts`,
  `nest::base::certs`, and source-built KasmVNC via `nest::lib::src_repo` and
  `nest::lib::build`
- `data/build/Gentoo/firefox/firefox.yaml` selects the build class for
  `build firefox zen5 ...`
- `plans/build/firefox.pp` wraps `nest::build::tool`, commits the image with
  `CMD=/usr/local/bin/nest-firefox-browser`, and runs a headless Firefox smoke
  test inside the build container
- `files/firefox-browser/build-kasmvnc.sh` builds the pinned KasmVNC checkout
  and its web client into `/opt/kasmweb` from the source-managed checkout
- `files/firefox-browser/nest-firefox-browser.sh` starts source-built KasmVNC
  `Xvnc` on 6901 and Portage Firefox with the existing `APP_ARGS` and
  `LAUNCH_URL` workload environment contract

Build/deploy should happen before the KubeCM cutover is accepted:

```sh
bin/build firefox zen5 deploy=true registry="$CI_REGISTRY" \
  registry_username="$CI_REGISTRY_USER" \
  registry_password_var=CI_REGISTRY_PASSWORD
bolt plan run nest::eyrie::ai::deploy_firefox
```

After rollout, rerun the ^1364 browser.eyrie matrix and compare each row against
the validated upstream `docker.io/kasmweb/firefox:1.18.0` baseline. A regression
in operator reachability, persistent profile state, Bitwarden/Joy takeover,
sanitized secure-browser actions, owner-only evidence routing, or final-purchase
negative gates blocks declaring parity.

## KasmVNC source-build notes

The upstream `kasmweb/firefox:1.18.0` canary proved the product shape. The Nest
`nest/tools/firefox` image now supplies Joy's Portage Firefox, fonts, CA trust,
Bitwarden extension policy, and a pinned source-built KasmVNC component. KasmVNC
continues to own browser-window/framebuffer behavior rather than relying on
noVNC client scaling. Any future parity regression should be fixed in this
source-managed KasmVNC/image path rather than returning to the upstream image as
the final state.
