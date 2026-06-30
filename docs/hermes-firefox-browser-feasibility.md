# Firefox feasibility for Hermes browser and secure-browser surfaces

## Scope

This report evaluates whether Joy's Hermes browser tooling and the shared
Kasm-backed secure browser can move from Chrome/Chromium to Firefox. It is an
investigation only: no production browser image, package, profile, or Kasm
workload was changed.

## Recommendation

Do not attempt a full Chrome/Chromium removal right now.

A partial migration is feasible and probably worth a follow-up prototype, but
only if the surfaces are split clearly:

1. Keep Chromium available for Hermes' built-in `browser_*` tools and any CDP
   driven automation.
2. Prototype Firefox/Camofox as an optional Hermes normal-browser backend where
   Joy wants Firefox-flavored behavior, accepting known gaps such as weaker
   console capture and a separate service dependency.
3. Prototype `kasmweb/firefox` only as a user-facing secure-browser UI after the
   automation contract is redesigned. The current secure-browser tools are
   Chrome DevTools Protocol clients and are not Firefox-compatible.

The best near-term target is therefore:

- normal Hermes browser tools: keep existing Chromium path; optionally add a
  source-managed Camofox canary
- secure browser: keep current `kasmweb/chrome` for Star/Talon guarded tools;
  optionally create a separate Firefox Kasm canary for manual Joy login/OAuth
  evaluation, with no final-purchase or CDP automation authority

## Current local evidence

From this worktree on `owl`/amd64:

- `agent-browser doctor` passes with `agent-browser` 0.31.1.
- Google Chrome is installed at `/usr/local/bin/google-chrome`.
- Chrome reports `Google Chrome 146.0.7680.177`.
- The doctor headless launch test passed in 0.23s.
- No `firefox` binary was found in the task PATH.

No live secure-browser/Kasm workload was modified or restarted.

## Current Hermes browser-tool dependency map

### Built-in `browser_*` tools

Relevant installed Hermes source files:

- `/opt/hermes-agent/src/tools/browser_tool.py`
- `/opt/hermes-agent/src/tools/browser_camofox.py`
- `/opt/hermes-agent/src/agent/browser_provider.py`
- `/opt/hermes-agent/src/agent/browser_registry.py`

The normal Hermes browser toolset currently has these backend classes:

- local `agent-browser` mode, described in source as headless Chromium via the
  `agent-browser` CLI
- cloud providers registered through the browser provider interface:
  Browser Use, Browserbase, and Firecrawl
- explicit CDP override mode through `BROWSER_CDP_URL` or `browser.cdp_url`
- optional Camofox mode through `CAMOFOX_URL`

The built-in tool surface includes navigation, accessibility snapshots,
click/type/press/scroll/back, console/eval, image listing, screenshots, and
vision analysis. Its local default is Chromium, not Firefox.

The requirements gate in `browser_tool.py` explicitly treats local Chrome mode
as satisfied by:

- `AGENT_BROWSER_EXECUTABLE_PATH`
- system `google-chrome`, `chromium`, `chromium-browser`, or `chrome`
- Playwright's Chromium/headless-shell cache

It does not treat a stock `firefox` binary as satisfying the default local
browser dependency. A Firefox swap at this layer would therefore need either
Camofox mode, a new browser backend, or upstream `agent-browser` support for a
Firefox engine.

### Puppet/Nest install path

Relevant Nest config file:

- `manifests/app/hermes/install.pp`

Current source-managed install behavior on amd64:

- installs `www-client/google-chrome`
- creates `/usr/local/bin/google-chrome -> /usr/bin/google-chrome-stable`
- installs `agent-browser@latest` globally through npm

This matches the current working local test: Hermes sees Chrome and
`agent-browser doctor` passes.

### Profile/toolset config

Relevant Nest config files:

- `manifests/app/hermes.pp`
- `manifests/lib/hermes.pp`

Current default Hermes profile toolsets include both `browser` and
`secure_browser`. Talon and Star profile configs both have:

- `browser.engine: auto`
- empty `browser.cdp_url`
- Camofox config present but not enabled

So the active default is Chromium-backed local browser tooling, not Firefox or
Camofox.

## Current secure-browser/Kasm dependency map

Relevant Nest config files:

- `data/kubernetes/app/secure-browser.yaml`
- `plans/eyrie/ai/deploy_secure_browser.yaml`
- `manifests/service/secure_browser.pp`
- `files/app/hermes/secure_browser_tool.py`
- `files/app/hermes/secure_browser_oauth_tool.py`

Current KubeCM source shape:

- image: `docker.io/kasmweb/chrome:1.18.0`
- public Kasm UI: `secure-browser.eyrie`
- CDP host: `secure-browser-cdp.eyrie`
- Chrome args include:
  - `--user-data-dir=/home/kasm-user/.config/secure-browser`
  - `--remote-debugging-address=0.0.0.0`
  - `--remote-debugging-port=9222`
- service exposes Kasm HTTPS on 6901 and a CDP proxy on 9222/9223
- a PVC persists `/home/kasm-user`
- Chrome enterprise policy mounts force-install Bitwarden using the Chrome
  extension id `nngceckbapebfimnlniiiahkandclblb`
- the reset-procedure text says OAuth and shopping share one browser process,
  one profile PVC, the Bitwarden extension install, and a Chrome DevTools
  endpoint

The custom secure-browser tools are direct CDP clients. They use `/json/version`,
`/json/list`, a browser websocket, and CDP domains/methods such as:

- `Target.getTargets`
- `Target.createTarget`
- `Target.attachToTarget`
- `Runtime.enable`
- `Runtime.evaluate`
- `Page.enable`
- `Page.navigate`
- `Page.captureScreenshot`

That is the decisive blocker for a drop-in Firefox replacement.

## Upstream/browser capability findings

### Hermes Agent docs

Hermes' current browser docs list multiple modes:

- Browserbase cloud
- Browser Use cloud
- Firecrawl cloud
- Camofox local mode
- local Chromium-family CDP via `/browser connect`
- local browser mode through `agent-browser`

The same docs describe Camofox as a self-hosted Node.js server wrapping
Camoufox, a Firefox fork, with a REST API intended to support Hermes browser
operations. That means Firefox-family support exists in Hermes, but it is not
the same dependency path as local `agent-browser` plus Google Chrome.

Source: https://hermes-agent.nousresearch.com/docs/user-guide/features/browser/

### Playwright

Playwright can launch and automate Chromium, Firefox, and WebKit through its
own browser APIs. It also has persistent contexts and screenshot/download-type
capabilities across browser engines.

But Playwright's `connectOverCDP` is Chromium-only. That matters because the
current secure-browser bridge and several Hermes browser-provider contracts are
CDP-shaped.

Source: https://playwright.dev/docs/api/class-browsertype

### Firefox remote automation

Firefox's supported remote automation direction is Marionette and WebDriver
BiDi, not Chrome DevTools Protocol. Mozilla's remote protocol docs list
Marionette and WebDriver BiDi. Selenium removed Firefox CDP support in 2025,
noting that Firefox CDP support was partial and that Firefox 129 stopped
enabling CDP by default.

Sources:

- https://firefox-source-docs.mozilla.org/remote/index.html
- https://www.selenium.dev/blog/2025/remove-cdp-firefox/

This means a Firefox secure-browser bridge should be designed around WebDriver
BiDi, Marionette/geckodriver, Playwright's Firefox protocol, or a Camofox-style
REST service. It should not depend on reviving Firefox CDP.

### Kasm Firefox image

Kasm publishes `kasmweb/firefox`. Docker Hub describes it as a browser-accessible
Mozilla Firefox image for Kasm Workspaces. It supports stand-alone deployment,
`LAUNCH_URL`, `APP_ARGS`, and `KASM_RESTRICTED_FILE_CHOOSER`, similar in spirit
to the Chrome image. Kasm notes that some features such as audio, uploads,
downloads, and microphone pass-through are only available when using Kasm
Workspaces orchestration.

Source: https://hub.docker.com/r/kasmweb/firefox/

So the Kasm UI layer can run Firefox. The automation layer is the blocker.

### Bitwarden extension deployment

Bitwarden documents managed extension deployment for Chrome and Firefox. The
Firefox extension uses:

- extension id: `446900e4-71c2-419f-a6a7-df9c091e268b`
- install/update URL:
  `https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi`

Source: https://bitwarden.com/help/browserext-deploy/

A Firefox Kasm migration would need Firefox policy files/paths and the Firefox
Bitwarden XPI policy, not the current Chrome `ExtensionInstallForcelist` JSON
and Chrome Web Store update URL.

## Capability comparison

### Normal Hermes `browser_*` tools

What works today with Chromium:

- local zero-cost headless browser through `agent-browser`
- accessibility snapshots and ref-based click/type/press/scroll
- screenshots and browser vision
- JavaScript eval and console/error collection
- CDP override for attaching to an existing Chromium-family browser
- cloud providers that return CDP URLs
- hybrid local sidecar behavior for private URLs while cloud providers handle
  public URLs

What Firefox can support through Camofox/Playwright-style APIs:

- navigation
- snapshots/accessibility trees
- click/type/press/scroll
- screenshots/vision
- persistent profile modes if explicitly configured

Known or likely changes/gaps:

- stock Firefox cannot satisfy the current `agent-browser` local Chromium
  requirement
- `/browser connect` CDP mode remains Chromium-family only
- cloud providers that expose CDP URLs remain Chromium-shaped
- Camofox currently reports console logs as unavailable in Hermes source
- Camofox is a separate server/service dependency with its own lifecycle,
  persistence, VNC, and loopback-network semantics
- any tests assuming exact Chromium accessibility tree shape, focus behavior, or
  bot-detection fingerprint will need cross-browser review

Recommendation for this layer: keep Chromium as the reliable default, and add a
Camofox canary only if Joy wants a Firefox-family testing target for ordinary
browser tasks.

### Secure browser / Kasm surface

What works today with Chrome/Kasm:

- Joy sees a persistent Kasm browser at the normal Eyrie HTTPS endpoint
- Bitwarden is force-installed using Chrome policy
- profile state persists on a PVC
- Star/Talon tools can claim owner-specific tabs through CDP target IDs
- tools can navigate, inspect sanitized page text, click/type bounded controls,
  take/redact screenshots, perform owner-only checkout review, and execute a
  final purchase only after a trusted approval gate
- guardrails are implemented in Python plus CDP page evaluation/click/screenshot
  operations

What Firefox/Kasm can support without bridge changes:

- user-facing browser UI
- manual Joy login/OAuth/shopping browsing
- persistent profile PVC, after profile path and seed logic are rewritten
- Firefox Bitwarden extension policy, after policy mounts are rewritten

What Firefox/Kasm cannot support as a drop-in replacement:

- Chrome remote debugging flags
- `/json/version` and `/json/list` CDP discovery
- current CDP websocket methods used by both secure-browser tool files
- owner-tab tracking by CDP target id
- CDP screenshots and Runtime.evaluate guardrail inspections
- current final-purchase executor implementation

Recommendation for this layer: do not switch the production secure browser to
Firefox until the automation bridge is redesigned and tested. If Joy wants a
Firefox UI, create a separate canary deployment first, with no exposed CDP
endpoint and no purchase authority.

## Security and privacy implications

Positive Firefox-side considerations:

- better alignment with Joy's non-Chrome personal browser preference
- reduced reliance on Google Chrome as the user-visible secure browser
- Firefox/Bitwarden managed extension deployment is documented and possible

Risks and tradeoffs:

- replacing CDP with WebDriver BiDi/Marionette/Playwright server would be a
  substantial security-sensitive rewrite of the secure-browser bridge
- WebDriver/BiDi endpoints must not be exposed publicly, just as raw CDP should
  not be model-visible or public
- Camofox's anti-detection features may be useful for ordinary browsing, but it
  is another service to source-manage, monitor, and patch
- Kasm standalone Firefox notes limited upload/download/microphone support
  outside full Kasm Workspaces orchestration
- Firefox profile and enterprise policy paths differ from Chrome, so careless
  migration could silently drop Bitwarden or profile persistence
- checkout/purchase guardrails depend on DOM inspection and click control; any
  new backend needs parity tests before it can be trusted with the approval gate

## Puppet/Nest changes required for a Firefox Kasm canary

A safe canary should be separate from the existing `secure-browser` deployment.
Do not mutate `secure-browser` in place for the first test.

Likely source changes:

1. Add a new KubeCM app data file, for example
   `data/kubernetes/app/secure-browser-firefox.yaml`.
2. Use `docker.io/kasmweb/firefox:<pinned version>` rather than a rolling tag.
3. Remove Chrome-only args:
   - `--remote-debugging-address`
   - `--remote-debugging-port`
   - Chrome-specific `--disable-features=UseChromeOSDirectVideoDecoder` if not
     verified for Firefox
   - Chrome `--user-data-dir` path
4. Replace Chrome profile seed logic with Firefox profile/PVC logic.
5. Replace Chrome policy ConfigMap mounts with Firefox policies, including the
   Bitwarden XPI install URL.
6. Do not expose `secure-browser-cdp.eyrie` or any replacement automation
   endpoint in the canary.
7. Keep Kasm UI ingress/TLS/PVC/readiness patterns from the current deployment.
8. Create a separate deploy plan, for example
   `plans/eyrie/ai/deploy_secure_browser_firefox.yaml`.
9. Verify KubeCM render output before live deployment.
10. Only after manual Joy validation, decide whether to build a Firefox-safe
    automation bridge.

## Bridge rewrite options for secure browser

If secure-browser automation must move to Firefox, the choices are:

1. WebDriver BiDi/geckodriver bridge
   - standards-aligned Firefox direction
   - would require rewriting tab ownership, navigation, eval, screenshot, and
     click/type helpers
   - likely safest long-term Firefox-native path

2. Playwright Firefox bridge
   - high-level API with Firefox support
   - can handle persistent contexts and screenshots
   - would need a controlled server/sidecar model to drive the browser in the
     Kasm session, not a separate invisible browser

3. Camofox-based bridge
   - already integrated with Hermes normal `browser_*` tooling
   - has REST endpoints for snapshots/click/type/screenshot
   - may not expose every guardrail primitive needed for final-purchase safety;
     console capture is currently unavailable

4. Keep Chrome for automation and add Firefox only for manual UI
   - least risky
   - satisfies most of Joy's "not personally Chrome" concern for manual use if
     the Firefox UI is the part Joy sees
   - still leaves Chromium installed for automation and fallbacks

## Migration plan

### Phase 0: keep current production unchanged

- Do not remove `www-client/google-chrome`.
- Do not change `data/kubernetes/app/secure-browser.yaml` production image.
- Do not remove the current CDP bridge.

### Phase 1: normal-browser Firefox-family canary

- Source-manage Camofox configuration for one non-production profile or dev
  profile.
- Enable via `CAMOFOX_URL` and optional `browser.camofox` settings.
- Run a small browser-tool parity checklist:
  - navigate public page
  - navigate private Eyrie page if policy allows
  - snapshot
  - click/type
  - screenshot/vision
  - JavaScript eval
  - console behavior
  - persistent profile behavior if desired
- Keep Chromium as fallback.

### Phase 2: Firefox Kasm manual UI canary

- Add a separate `kasmweb/firefox` KubeCM app with its own hostname/PVC.
- Install Bitwarden through Firefox policy.
- Verify manual Joy flows:
  - Kasm connection
  - Bitwarden extension present
  - login/passkey/2FA UX
  - OAuth/device-code flow
  - Amazon/product/cart pages for manual browsing only
  - profile persistence across pod restart
- Do not wire Star's current secure-browser tools to this canary.

### Phase 3: automation bridge decision

After Phase 2, choose one:

- keep Firefox as manual-only and Chrome as automation backend
- build a WebDriver BiDi/Playwright/Camofox bridge behind the same
  `secure_browser_*` privacy contract
- abandon Firefox Kasm if the operational burden is not worth it

### Phase 4: guarded production switch only after parity

Only if a new bridge passes parity and guardrail tests:

- add source-managed rollback to the Chrome deployment
- deploy to dev/canary first
- test final-purchase approval refusal/success paths with synthetic pages, not
  live purchases
- run Joy-supervised live OAuth/shopping validation
- switch production only through an explicit Joy-approved Agent Request

## Rollback

Normal browser tools:

- unset `CAMOFOX_URL`
- remove/disable Camofox config
- keep or restore `browser.engine: auto`
- verify `agent-browser doctor` passes with Chrome
- restart affected Hermes gateway sessions if needed

Secure browser:

- keep the existing `data/kubernetes/app/secure-browser.yaml` Chrome deployment
  unchanged during canary work
- if a Firefox canary fails, delete or scale down only the canary deployment and
  preserve the production `secure-browser` PVC/deployment
- if a production switch ever happens, rollback should restore the previous
  `kasmweb/chrome` image, Chrome args, Chrome policy mounts, CDP service, and
  Chrome profile PVC snapshot/backup

## Recommended next requests

1. Camofox normal-browser canary for Talon
   - repo: Nest config plus Hermes config as needed
   - goal: source-manage and validate a non-production Camofox backend for
     normal `browser_*` tools
   - non-goal: no secure-browser or shopping/final-purchase changes

2. Firefox Kasm manual secure-browser canary
   - repo: Nest config
   - goal: add a separate `kasmweb/firefox` KubeCM app with Firefox Bitwarden
     policy and persistent profile, manual Joy validation only
   - non-goal: no Star guarded tool wiring and no purchase authority

3. Secure-browser automation backend design
   - repo: Nest config and Hermes secure-browser tool source
   - goal: design WebDriver BiDi/Playwright/Camofox bridge parity requirements
     and guardrail tests before any implementation
   - non-goal: no production switch until design and canaries are accepted

## Bottom line

Firefox can participate in Joy's browser stack, but it is not a drop-in
replacement for the current Chrome/Chromium foundation.

The normal Hermes browser tools already have a Firefox-family path through
Camofox, but the reliable installed default remains local Chromium through
`agent-browser`. The secure-browser surface is much more Chrome-specific: both
its KubeCM deployment and its custom tools are built around Chrome policy,
Chrome profile layout, and Chrome DevTools Protocol. A user-facing Firefox Kasm
canary is safe to investigate, but production guarded secure-browser automation
should remain Chromium until a new non-CDP bridge exists and passes guardrail
parity tests.
