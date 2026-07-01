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
- upstream image: `docker.io/kasmweb/firefox:1.18.0`

The app exposes the KasmVNC/noVNC Firefox UI through a Contour `HTTPProxy` with
websocket support. It deliberately exposes no Camofox REST API, CDP, WebDriver,
Marionette, raw VNC credentials, cookies, storage, request headers, screenshots
of secret pages, vault data, payment/address details, or direct final-purchase
authority to models.

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
remain source-managed for rollback and for the current Hermes secure-browser
backend until the Firefox bridge below is implemented and parity-tested.

## Automation bridge options

### CDP

Firefox CDP support is incomplete compared with Chrome and does not match the
existing Star secure-browser implementation closely enough to make a blind
endpoint swap safe. Exposing a raw CDP-like endpoint would also make cookies,
storage, network events, screenshots, and final controls too easy to leak or
misuse.

Verdict: do not expose raw CDP from `browser.eyrie`. Keep Chrome/Kasm CDP as the
rollback/current backend until a narrow Firefox bridge exists.

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

## Future image milestone

The upstream `kasmweb/firefox:1.18.0` canary is intentionally narrow. A future
`nest/tools/firefox` image can use Joy's Portage Firefox, fonts, CA trust,
KasmVNC integration, and extension/native-helper packaging once the upstream
canary proves the product shape and bridge contract.
