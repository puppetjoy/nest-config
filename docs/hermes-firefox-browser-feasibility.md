# Camofox migration plan for Hermes browser and secure-browser surfaces

## Scope

Joy asked for the investigation to stop treating Firefox/Camofox as an optional
limited canary and instead answer the practical question: if Chrome is going
away, what do we actually need to build so Hermes browser tooling and the
secure-browser/shopping tools run on Camofox?

This report is still investigative only. I did not remove Chrome, deploy
Camofox, change the production `secure-browser` workload, or alter live shopping
or OAuth tooling.

## Bottom line

A Chrome-removal path is feasible, but it is not a one-line image swap. The
right target is not stock Firefox or `kasmweb/firefox`; it is a Camofox Browser
service, because Hermes already has first-class Camofox integration and Camofox
Browser gives us the pieces Joy cares about:

- Camoufox/Firefox engine with anti-detection/fingerprint work
- REST API with tabs, accessibility snapshots, element refs, click/type/press,
  screenshots, links/images, downloads, traces, cookie/session endpoints, and
  JavaScript evaluation
- optional noVNC/VNC for Joy-operated login, CAPTCHA, OAuth, Bitwarden, and
  checkout supervision
- persistent profile/session directories that can live on Kubernetes PVCs

The main work is replacing Joy's custom secure-browser bridge from direct
Chrome DevTools Protocol (CDP) calls to Camofox Browser's REST/session model,
then validating the shopping/checkout guardrails against that backend. The
built-in Hermes `browser_*` tools are much closer: `/opt/hermes-agent` already
has a Camofox backend and can route there when `CAMOFOX_URL` is set.

Recommended direction: do the migration in two source-managed tracks:

1. General Hermes browser service: Camofox Browser container exposed only to
   Hermes profiles, with `CAMOFOX_URL` and persistent identity settings.
2. Secure browser service: separate Camofox Browser container with noVNC for
   Joy and a private REST API for the `secure_browser_*` tools, plus a rewritten
   secure-browser adapter preserving the existing privacy/approval contract.

Chrome can be removed after these two tracks pass parity. Until then, removal is
an implementation milestone, not the first step.

## What exists today

### Hermes normal browser tools

Relevant installed Hermes files:

- `/opt/hermes-agent/src/tools/browser_tool.py`
- `/opt/hermes-agent/src/tools/browser_camofox.py`
- `/opt/hermes-agent/src/tools/browser_camofox_state.py`
- `/opt/hermes-agent/src/agent/browser_provider.py`
- `/opt/hermes-agent/src/agent/browser_registry.py`

Current local evidence on owl:

- `agent-browser doctor` passed with `agent-browser` 0.31.1.
- Google Chrome is installed at `/usr/local/bin/google-chrome`.
- Chrome reports `Google Chrome 146.0.7680.177`.
- No production browser package or workload was changed during this task.

Hermes already supports Camofox mode. `browser_camofox.py` says that when
`CAMOFOX_URL` is set, browser tools route through the Camofox backend instead
of the `agent-browser` CLI. It implements:

- navigate
- snapshot/accessibility tree
- click
- type
- scroll
- back
- press
- close
- image discovery from the accessibility snapshot
- screenshot + vision analysis
- managed persistence using `browser.camofox.managed_persistence`
- configured identity override via `CAMOFOX_USER_ID` / `CAMOFOX_SESSION_KEY`
- existing-tab adoption via `CAMOFOX_ADOPT_EXISTING_TAB`
- Docker loopback URL rewriting via `CAMOFOX_REWRITE_LOOPBACK_URLS`

Known gap: Hermes' current Camofox backend returns an empty console result with
a note because Camofox Browser's REST API does not expose browser console logs
through that Hermes adapter. That is a real change from local Chromium mode, but
not a blocker for ordinary browsing if we accept snapshot/vision/query-based
inspection.

### Nest/Puppet install path

Relevant Nest config files:

- `manifests/app/hermes/install.pp`
- `manifests/app/hermes.pp`
- `manifests/lib/hermes.pp`
- `data/host/owl.yaml`

Current source-managed behavior on amd64 installs Chrome and `agent-browser`:

- `www-client/google-chrome`
- `/usr/local/bin/google-chrome -> /usr/bin/google-chrome-stable`
- global npm `agent-browser@latest`

Talon and Star profile config currently keeps `browser.engine: auto`, an empty
`browser.cdp_url`, and Camofox config present but not enabled. So the live
default is still Chromium-backed unless `CAMOFOX_URL` is injected.

### Current secure-browser/shopping surface

Relevant Nest config files:

- `data/kubernetes/app/secure-browser.yaml`
- `plans/eyrie/ai/deploy_secure_browser.yaml`
- `manifests/service/secure_browser.pp`
- `files/app/hermes/secure_browser_tool.py`
- `files/app/hermes/secure_browser_oauth_tool.py`

Current KubeCM deployment shape:

- image: `docker.io/kasmweb/chrome:1.18.0`
- public UI: `secure-browser.eyrie` on Kasm HTTPS port 6901
- CDP host: `secure-browser-cdp.eyrie`
- Chrome args include:
  - `--user-data-dir=/home/kasm-user/.config/secure-browser`
  - `--remote-debugging-address=0.0.0.0`
  - `--remote-debugging-port=9222`
- PVC persists `/home/kasm-user`
- Chrome policy force-installs Bitwarden using extension id
  `nngceckbapebfimnlniiiahkandclblb`
- CDP proxy exposes the browser's local port 9222

The custom secure-browser tools are CDP clients today. They discover and drive
pages via:

- `/json/version`
- `/json/list`
- browser websocket URL
- `Target.getTargets`
- `Target.createTarget`
- `Target.attachToTarget`
- `Runtime.enable`
- `Runtime.evaluate`
- `Page.enable`
- `Page.navigate`
- `Page.captureScreenshot`

The public tool contract is broader than those primitives. Star's
`secure_browser_*` toolset currently promises:

- navigate ordinary shopping/account-research pages
- sanitized visible text and interactive selectors
- bounded read-only query
- safe click/type with explicit approved effects
- redacted screenshots/visual evidence
- owner-only checkout review sent directly to Joy
- material-summary binding and trusted final-purchase approval
- exactly-once final purchase execution after approval
- order ledger/refresh and consumable tracking

That contract can survive Camofox, but the implementation underneath must be
rewritten. The existing CDP calls cannot simply point at Firefox/Camofox.

## Upstream Camofox/Camoufox facts that matter

Sources checked:

- Hermes browser docs:
  `https://hermes-agent.nousresearch.com/docs/user-guide/features/browser/`
- `jo-inc/camofox-browser` README and OpenAPI/docs
- Camofox Browser VNC plugin docs
- Camofox Browser deployment/Docker docs
- Camoufox docs:
  `https://camoufox.com/` and `https://camoufox.com/stealth/`
- Camoufox Juggler source directory summary
- Bitwarden managed browser extension deployment docs

Key findings:

- Hermes docs explicitly list Camofox local mode as a supported browser backend.
- Camofox Browser is a self-hosted Node/Express REST server wrapping Camoufox.
  Default API port is 9377.
- Camofox Browser's public API model is tabs/sessions, not raw CDP. Documented
  endpoint families include `/tabs`, `/tabs/:id/navigate`, `/tabs/:id/click`,
  `/tabs/:id/type`, `/tabs/:id/press`, `/tabs/:id/scroll`,
  `/tabs/:id/snapshot`, `/tabs/:id/screenshot`, `/tabs/:id/links`,
  `/tabs/:id/extract`, session cookie/trace endpoints, health, metrics, and
  cleanup.
- Camofox Browser supports noVNC/VNC as an interactive browser UI. The VNC plugin
  is explicitly intended for visual login, MFA, CAPTCHA, OAuth, and then reuse
  of authenticated storage state.
- Camofox Browser Docker deployment uses a persistent data path under
  `/home/node/.camofox`, including profiles/downloads. Docker examples expose
  port 9377 for REST and 6080 for noVNC.
- Camoufox is Firefox-based and uses Playwright's Firefox/Juggler path rather
  than Chromium CDP as its preferred automation layer. Camoufox docs explicitly
  call CDP a common bot-detection target and describe Juggler as lower-level and
  less prone to JavaScript leaks.
- Camoufox's own docs warn that 2026 releases are active/experimental and may
  introduce breaking changes. That makes pinning and staged validation more
  important than with a boring distro Firefox.
- Bitwarden has Firefox managed extension deployment. The Firefox extension id
  is `446900e4-71c2-419f-a6a7-df9c091e268b`, with latest XPI URL
  `https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi`.

## What we would actually build

### 1. Source-managed Camofox Browser image/runtime

Do not depend on `npx` downloading a browser at pod startup. Source-manage one
of these:

- a pinned upstream Camofox Browser image if Joy accepts upstream image trust and
  tag cadence, or
- a Nest-built `registry.eyrie/nest/camofox-browser:<pinned>` image built from a
  pinned Camofox Browser release, pre-fetching the Camoufox binary during the
  image build.

The Nest-built image is more work but better matches Joy's source-managed
rollout style and avoids runtime network fetches for a security-sensitive
browser.

Required container properties:

- REST API on 9377
- noVNC web UI on 6080 for secure-browser, optional/disabled for headless
  general Hermes browser
- persistent mount at `/home/node/.camofox`
- health check against `/health`
- access key/API key support enabled for non-loopback Kubernetes access
- no public exposure of the REST API
- logs without URLs, cookies, secrets, vault data, checkout details, or raw page
  text

### 2. General Hermes Camofox service

Add a non-shopping Camofox app, for example:

- `data/kubernetes/app/hermes-camofox.yaml`
- `plans/eyrie/ai/deploy_hermes_camofox.yaml`
- service DNS visible only inside Nest/Eyrie private network
- PVC for `/home/node/.camofox`
- API endpoint like `http://hermes-camofox.ai.svc.cluster.local:9377` or a
  private Eyrie hostname if profiles need host access

Then set per-profile config/env, probably in Nest-managed Hermes profile
settings:

- `CAMOFOX_URL=<private service URL>`
- `browser.camofox.managed_persistence: true` where persistent sessions are
  wanted
- stable `CAMOFOX_USER_ID`/`CAMOFOX_SESSION_KEY` only where one profile should
  reuse a visible/persistent browser identity
- `CAMOFOX_REWRITE_LOOPBACK_URLS` only for container-to-host local app flows

Validation for the general browser track:

- `browser_navigate` public site
- private Eyrie URL if policy allows
- snapshot refs
- click/type/press/scroll
- screenshot/vision
- read-only page state via snapshot/vision rather than console logs
- persistence across gateway restart and pod restart
- behavior when Camofox is down, including clear tool errors and no fallback to
  Chromium once Chrome removal is in scope

Expected loss/change vs current Chromium path:

- no `/browser connect`-style arbitrary CDP attachment to Chrome/Brave/Edge
- console collection remains unavailable unless upstream Camofox Browser or
  Hermes Camofox backend adds it
- accessibility tree and focus behavior may differ from Chromium
- Camofox service health becomes a required platform dependency

### 3. Secure Camofox service replacing Kasm Chrome

The secure-browser replacement should not be `kasmweb/firefox`. It should be a
Camofox Browser deployment with the VNC plugin/noVNC enabled, because that gives
us both sides we need: Joy's visual browser and Star/Talon's automation API
against the same browser engine/profile.

Proposed source shape:

- `data/kubernetes/app/secure-browser-camofox.yaml`
- `plans/eyrie/ai/deploy_secure_browser_camofox.yaml`
- optional new class/define if the existing `nest::service::secure_browser`
  should remain Chrome-specific during migration
- public/private UI hostname such as `secure-browser.eyrie` only after cutover;
  before cutover use a separate canary hostname such as
  `secure-browser-camofox.eyrie`
- private REST hostname/service only for Hermes tools, never exposed as a raw
  user-facing public endpoint
- PVC mounted at `/home/node/.camofox`
- `ENABLE_VNC=1`
- `VNC_RESOLUTION=1920x1080`
- VNC password or equivalent ingress boundary; today's Kasm deployment disables
  Basic Auth and relies on Eyrie-private network boundaries, but Camofox noVNC
  docs warn VNC is unencrypted/open by default, so we should be more explicit
  about ingress/network policy and whether Joy wants a password layer
- Camofox access/API key secret mounted from eyaml/Kubernetes secret

Firefox/Bitwarden policy work:

- replace Chrome policy JSON and extension update URLs with Firefox policy
- use Bitwarden Firefox extension id
  `446900e4-71c2-419f-a6a7-df9c091e268b`
- install XPI from Bitwarden's documented AMO latest URL unless we choose to
  mirror/pin the XPI internally
- verify the extension is present in the VNC UI before any OAuth/shopping test
- decide whether the Bitwarden extension state lives in the Camofox profile PVC
  or needs seeded policy/default-profile files in the image/container

Profile migration work:

- the existing Chrome profile under `/home/kasm-user/.config/secure-browser`
  cannot be copied into Firefox/Camofox as-is
- plan a new Camofox/Firefox profile, manual Joy login/unlock, and fresh
  Bitwarden/OAuth/shopping state
- keep old Chrome PVC snapshot until rollback is no longer needed

### 4. Rewrite secure-browser tools as a backend adapter

The current `files/app/hermes/secure_browser_tool.py` and
`secure_browser_oauth_tool.py` should keep their public tool names and privacy
boundaries, but their browser-driving layer should become backend-swappable:

- `ChromeCdpSecureBrowserBackend` for temporary rollback during migration
- `CamofoxSecureBrowserBackend` for the new path

The backend interface should cover the primitives the tools actually need:

- status/health
- list/adopt/create owner tab
- navigate URL
- current URL/title
- read visible text and interactive controls
- evaluate a constrained read-only expression or equivalent structured query
- click selector/ref
- type bounded text
- press key
- screenshot viewport/full page
- visual evidence/crop source image
- owner-only screenshot capture
- close/reset owner tab mapping

Camofox mapping:

- owner mapping: `owner -> userId/sessionKey/tabId`, stored in the existing
  ownership state file or a new backend-neutral state file
- tab adoption: use `GET /tabs?userId=...` and `listItemId`/`sessionKey`
- navigation: `POST /tabs/:tabId/navigate`
- snapshots: `GET /tabs/:tabId/snapshot`
- click/type/press/scroll: Camofox interaction endpoints
- screenshots: `GET /tabs/:tabId/screenshot`
- extraction: `/tabs/:tabId/extract` after snapshot where useful
- read-only JS: Camofox Browser OpenAPI includes an interaction/evaluate area;
  use that if available in the pinned version, otherwise replace risky generic
  JS evaluation with structured extraction and a small set of server-side helper
  endpoints we own

The biggest technical question is not "can Camofox click and screenshot?" It can.
The question is whether our current Amazon checkout sanitizers, redaction
rectangle discovery, and final-purchase material-summary binding can be ported
without relying on broad raw DOM/JS access in a way that weakens the safety
boundary. For that reason, the adapter must come with parity tests before the
Chrome backend is removed.

### 5. Preserve secure-browser safety semantics

These invariants must not change during the migration:

- Star/Talon do not receive cookies, local storage, request headers, vault data,
  passwords, 2FA, CAPTCHA, passkeys, raw payment/account details, raw full
  address/contact details, or raw checkout screenshots
- login, Bitwarden unlock, passkeys, 2FA, CAPTCHA, suspicious prompts, payment,
  address, and account edits stay Joy-operated through the visible browser
- final Buy Now/Place Order controls remain blocked from ordinary tool calls
- final purchase still requires:
  1. owner-only checkout review sent directly to Joy
  2. material summary binding
  3. trusted Agent Request approval
  4. live re-read/revalidation
  5. exactly-one final control action
  6. post-purchase proof handling without exposing secrets
- order ledger and consumable tools remain sanitized ledgers, not raw browser
  session dumps
- raw Camofox REST/VNC/control endpoints stay outside model-visible outputs

## Capability comparison after Camofox migration

### Gains

- Removes Chrome/Kasm from the user-facing browser story
- Aligns with Joy's non-Chrome preference
- Uses Hermes' existing Camofox backend for normal browser tools
- Gains Camofox/Camoufox anti-detection features and fingerprint consistency
  work
- VNC/noVNC can replace Kasm for owner-operated login/OAuth/checkout review
- Potentially lower browser memory footprint than Chrome/Kasm, subject to live
  measurement on owl/Eyrie
- One Camofox API model can serve both headless agent browser tasks and the
  visible secure-browser session

### Losses or changed behavior

- Direct CDP is gone. Existing CDP code must be rewritten, not reconfigured.
- `/browser connect` to arbitrary local Chromium-family browsers is no longer a
  Chrome-free feature.
- Console log capture is not currently supported by Hermes' Camofox adapter.
- Camofox 2026 releases are explicitly active/experimental; pinned versions and
  rollback matter.
- noVNC security is different from KasmVNC. We must design auth/network policy
  instead of inheriting Kasm's behavior.
- Existing Chrome profile state cannot be reused directly.
- Browser accessibility trees, selectors, screenshots, and Amazon checkout DOM
  behavior may differ and must be retuned.

### Unknowns requiring prototype evidence

- Exact Firefox policy path inside the chosen Camofox Browser image for managed
  Bitwarden install
- Whether the pinned Camofox Browser version's evaluate endpoint is sufficient
  for all existing checkout sanitizers, or whether we need custom helper
  endpoints
- Whether Amazon login/cart/checkout pages behave better, worse, or differently
  under Camofox fingerprints from Joy's Eyrie IPs
- Whether Camofox VNC UX is good enough for Joy compared with Kasm
- Whether profile persistence handles Bitwarden extension state cleanly across
  pod restarts
- Resource usage under one persistent secure-browser profile plus concurrent
  general Hermes browsing sessions

## Concrete migration plan

### Phase 0: pin and build Camofox Browser

Goal: produce a source-managed Camofox Browser runtime without touching live
secure-browser.

Tasks:

1. Choose upstream release/tag, starting from Camofox Browser 1.11.2 or newer
   after checking changelog/stability.
2. Decide upstream image vs Nest-built image. I recommend Nest-built for the
   secure-browser path.
3. Build/push `registry.eyrie/nest/camofox-browser:<version>-nest` with Camoufox
   binary pre-fetched.
4. Add minimal KubeCM app for a private `hermes-camofox` service.
5. Add secrets/config for Camofox access/API/admin keys.
6. Verify `/health`, REST auth, noVNC disabled/enabled modes, PVC persistence,
   and resource limits.

Validation:

- Kubernetes pod healthy
- `/health` reports browser-ready state
- creating a tab works
- snapshot, click/type, screenshot work
- pod restart preserves configured profile/session state where expected

Rollback:

- delete/scale only the Camofox app
- leave existing Chrome/Kasm secure-browser untouched

### Phase 1: move general Hermes browser tools to Camofox

Goal: make ordinary `browser_*` use Camofox without touching shopping tools.

Tasks:

1. Add Nest-managed per-profile `CAMOFOX_URL` and `browser.camofox` config for a
   target profile.
2. Enable managed persistence only where useful; keep ephemeral sessions for
   generic throwaway browsing if preferred.
3. Remove or disable Chromium fallback in that profile's browser path once
   Camofox checks pass, so failures are visible instead of silently using
   Chrome.
4. Run the Hermes browser parity checklist.

Validation checklist:

- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_press`
- `browser_scroll`
- `browser_vision`
- image listing expectations
- failure when Camofox is unavailable is clear and actionable
- no accidental Chrome process used for these tool calls

### Phase 2: create secure-browser Camofox canary

Goal: give Joy a visible Camofox browser with persistent state and Bitwarden,
without purchase authority yet.

Tasks:

1. Add `secure-browser-camofox` KubeCM app using the pinned Camofox Browser
   image.
2. Enable VNC/noVNC and expose only the Joy-facing UI hostname.
3. Keep REST API private to Hermes/Nest networks.
4. Mount a fresh PVC for `/home/node/.camofox`.
5. Add Firefox/Bitwarden policy or profile seeding.
6. Add reset/revoke procedure equivalent to the current ConfigMap, but written
   for Camofox profiles and Camofox API keys.
7. Verify manual Joy flows before any automation wiring.

Validation checklist:

- noVNC page loads through Eyrie
- Bitwarden extension is installed and visible
- Joy can unlock/use Bitwarden manually
- OAuth/device flow can be completed manually
- Amazon login/product/cart pages can be reached manually
- profile and extension state survive pod restart
- no raw REST/API endpoint is exposed publicly

### Phase 3: implement Camofox secure-browser backend

Goal: port the secure-browser/shopping tools to Camofox while keeping tool names
and safety behavior.

Tasks:

1. Refactor current secure-browser tool code to isolate CDP calls behind a
   backend interface.
2. Implement `CamofoxSecureBrowserBackend` against Camofox REST.
3. Map selectors/refs carefully. Current public tools accept CSS selectors;
   Camofox's strongest model is element refs from snapshots. We can either:
   - translate safe CSS selectors through a constrained evaluate/locator helper,
   - change internal suggested selectors to Camofox refs while keeping public
     tool schema stable, or
   - return both `selector` and `ref` during transition.
4. Port sanitizers and checkout summary extraction.
5. Port screenshot/redaction pipeline to Camofox screenshot PNGs.
6. Port owner-only checkout review and material-summary binding.
7. Port final-purchase executor only after synthetic parity tests pass.
8. Keep `ChromeCdpSecureBrowserBackend` available behind config until Camofox is
   accepted.

Required tests:

- backend fake tests for owner tab mapping/adoption
- fake Camofox REST server tests for navigation/snapshot/click/type/screenshot
- sanitizer tests using captured/synthetic Amazon-like HTML states
- screenshot redaction tests using generated images, not live secrets
- final purchase refusal tests: no approval, stale binding, changed material
  summary, multiple final controls, login/security prompt visible
- final purchase success test on a synthetic page only
- order ledger refresh path still sanitized
- no tool result contains raw Camofox URL, API key, cookies, local storage,
  request headers, vault content, full address/payment, or unredacted checkout
  evidence

### Phase 4: switch secure-browser production endpoint

Goal: replace Chrome/Kasm only after parity.

Tasks:

1. Snapshot/backup old Chrome secure-browser PVC.
2. Keep old deployment scaled down but restorable for a defined rollback window.
3. Point `SECURE_BROWSER_PUBLIC_URL` and backend config to the Camofox service.
4. Remove `SECURE_BROWSER_CDP_URL` dependency for Camofox mode.
5. Run Joy-supervised live OAuth/shopping validation.
6. Only then remove Chrome/Kasm source references and package installs.

Validation:

- secure browser status reports Camofox backend
- no Chrome/Kasm pod is serving the active endpoint
- Bitwarden still available
- owner-only checkout review reaches Joy
- approval gate refuses/accepts only as expected on synthetic pages
- live shopping browsing works with Joy supervision
- no Chrome process/package is required by active Hermes browser/secure-browser
  paths

## Puppet/Nest changes likely required

Source changes in `nest/config`:

- Camofox image build source or KubeCM app image reference
- new Hiera/KubeCM app data for `hermes-camofox`
- new Hiera/KubeCM app data for `secure-browser-camofox`
- deploy plans for both apps
- DNS entries for any private/public Eyrie hostnames
- cert-manager/ingress resources for the noVNC UI
- Kubernetes secrets for Camofox access/API/admin keys
- PVC definitions for `/home/node/.camofox`
- Firefox/Bitwarden policy/profile seed ConfigMaps or image assets
- Hermes profile env/config for `CAMOFOX_URL`, persistence, identity, and secure
  backend selection
- secure-browser tool code copied by `manifests/app/hermes/install.pp`
- reset/revoke procedure docs for Camofox profile and keys
- eventual removal of `www-client/google-chrome`, `agent-browser`, Chrome/Kasm
  args, Chrome policy mounts, and `secure-browser-cdp.eyrie` only after parity

## Recommended next Agent Requests

1. Build/deploy private Camofox Browser runtime for Hermes
   - repo: Nest config
   - goal: source-managed pinned Camofox Browser image/app with REST health,
     private API, optional noVNC, PVC persistence, and no production secure
     browser changes
   - follow-through: deploy canary and verify live health

2. Move one Hermes profile's normal `browser_*` tools to Camofox
   - repo: Nest config and Hermes profile config
   - goal: configure `CAMOFOX_URL` and Camofox persistence for Talon or a dev
     profile, run browser tool parity, prove Chrome is not used for those calls
   - non-goal: secure-browser/shopping tools

3. Create secure-browser Camofox UI canary with Bitwarden
   - repo: Nest config
   - goal: Camofox noVNC UI, persistent profile, Firefox Bitwarden install,
     Joy manual OAuth/shopping validation
   - non-goal: final purchase/tool automation authority

4. Implement Camofox backend for `secure_browser_*`
   - repo: Nest config plus Hermes secure-browser tool source
   - goal: backend abstraction, Camofox adapter, parity tests, synthetic checkout
     approval/refusal tests, no secret leakage
   - non-goal: production endpoint switch until reviewed

5. Remove Chrome/Kasm after Camofox parity
   - repo: Nest config
   - goal: switch production endpoints, retire Chrome/Kasm/CDP service/package
     dependencies, verify rollback and live paths
   - precondition: phases 1-4 accepted and deployed

## Answer to Joy's specific question

What would we actually need to do to get this working with the
secure-browser/shopping tools?

We need to stop thinking of Camofox as "Firefox pretending to provide CDP" and
instead make Camofox Browser the browser service. For normal Hermes browsing,
that is mostly configuration plus a source-managed service because Hermes
already has a Camofox backend. For secure browsing, we need a new backend under
our `secure_browser_*` tools that drives the same visible Camofox/noVNC session
through Camofox Browser's REST API, not Chrome CDP.

The work is real but bounded: build/deploy Camofox Browser, install Bitwarden in
its Firefox profile, persist `/home/node/.camofox`, expose noVNC to Joy, keep the
REST API private, refactor secure-browser tools behind a backend adapter, port
navigation/snapshot/click/type/screenshot/query/redaction/final-approval
primitives, and prove with synthetic checkout tests that the approval gate still
cannot leak secrets or click Place Order without the exact trusted approval.

If those tests pass, Chrome and Kasm can go away. If they fail, the likely
failure point will not be Camofox's basic browsing ability; it will be one of
our high-trust shopping guardrails needing a Camofox-specific extraction or
redaction implementation.
