# Persistent Firefox OS/UI control architecture

## Decision

`browser.eyrie` is one ordinary visible Firefox desktop backed by one durable
local profile. Star controls that desktop through X11 input, AT-SPI
accessibility readback, and visible-window screenshots. The browser process has
no WebDriver, Marionette, BiDi, CDP/Remote Debugging flags, automation extension,
injected navigator changes, or hidden parallel context.

Joy's direction to Star for a workflow is the authorization boundary. The
platform does not add per-click, cart, checkout, or purchase approval prompts.
Fresh readback and stable action keys are correctness properties, not approval
gates. Passwords, passkeys, 2FA/CAPTCHA values, card/account numbers, tokens,
cookies, storage, and raw Firefox profile content remain outside agent-visible
text and logs. Phase 1 deliberately disables Firefox Accounts/Sync; Sync is not
a prerequisite and may be reconsidered only if Joy later requests it.

This is not fingerprint spoofing or anti-bot evasion. It removes automation
instrumentation and uses Firefox's normal supported desktop UI. Retailer denials
remain authoritative and must not be bypassed.

## Deployed-stack inventory before migration

The production workload is the singleton `ai/deployment/firefox`, published at
`browser.eyrie` through KasmVNC and backed by the `firefox-profile` PVC mounted
as `/home/kasm-user`. The image is the Nest Portage Firefox tool image. The
pre-migration process was observed with Firefox Remote Debugging flags and a CDP
route/service. The profile itself was not inspected.

The workload has no HTTP(S) proxy environment. Its NetworkPolicy denies cloud
metadata/link-local destinations but otherwise uses the cluster's ordinary
outbound route. Therefore the MSC incident cannot be attributed to an explicit
application proxy configured in this workload. The displayed security-service
denial is compatible with browser instrumentation, upstream/transparent network
reputation, stale browser state, or a combination. Phase 1 compares an
uninstrumented clean-profile canary on the same ordinary route before proposing
any egress change. No displayed network identifier is recorded here.

The supplied incident screenshot established two facts without being copied
into source: many repeated Amazon tabs were open, and MSC returned a
security-service denial that displayed origin/proxy information. It did not by
itself isolate causality.

## Source-managed implementation

- `files/firefox-browser/nest-firefox-browser.sh` starts the visible Firefox
  profile, rejects automation-specific `APP_ARGS`, and starts a private desktop
  D-Bus/AT-SPI session.
- `files/firefox-browser/firefox-ui-bridge.py` is invoked inside the Firefox
  container. It has no network listener and no browser/profile API. It uses
  `xdotool`, AT-SPI, and `ffmpeg` X11 capture only.
- `files/app/hermes/secure_browser_tool.py` is the Hermes adapter. It invokes the
  bridge with `kubectl exec`, bounds results, emits `firefox-ui-v1`, and makes
  unsupported DOM behavior explicit.
- `files/app/hermes/secure_browser_legacy_support.py` temporarily retains only
  the separately exposed `retail_order_*` and `consumable_*` state tools. Its
  registry filter prevents the retired CDP browser handlers from registering.
- `files/app/hermes/skills/star-firefox-ui/SKILL.md` is installed into Star's
  profile and overrides stale browser-control advice in the accumulated
  shopping skill without discarding its product, sizing, retailer, and
  post-purchase knowledge.
- `data/kubernetes/app/firefox.yaml` removes the Remote Debugging args, port,
  proxy sidecar, service port, DNS name, certificate name, and ingress. It keeps
  the owner-visible Kasm endpoint and durable profile PVC.
- `data/host/owl.yaml` replaces the CDP URL with the versioned UI-control mode
  and bridge path for Star and Talon.

## Control and continuity model

A workflow first explicitly acquires one canonical handoff tab. Navigation,
snapshot, click, and type never create tabs implicitly. A selected blank tab may
be claimed without ownership; otherwise acquire creates exactly one agent-owned
tab below the hard cap. Every mutating input is followed by accessibility
readback.

The bridge stores only non-secret workflow metadata in mode `0600`: workflow
identifier, browser generation, accessibility locator/title identity,
ownership flag, lease expiry, uncertainty flag, and action-key timestamps. It
does not store URLs with queries, page text, field values, cookies, profile
paths, or credentials.

On restart the bridge rebinds a workflow only when exactly one local tab matches
the prior non-secret identity. Missing or duplicate matches become uncertain;
the bridge preserves all tabs and refuses input rather than silently claiming or
closing a Joy-owned tab. Expired confidently agent-created tabs close once.
Claimed Joy-owned blank tabs are released without closing. Keep-open leases are
bounded, and the hard cap refuses new tabs rather than deleting unknown tabs.
Firefox Sync remote-tab history is not read and is not counted as local tabs.

An `action_key` gives at-most-once delivery across acknowledged retries. It is
persisted even if post-click readback fails, preventing a blind second click.
No UI automation layer can provide a true atomic exactly-once transaction with
an arbitrary retailer; post-action readback and retailer confirmation remain
required before claiming success.

Visible interactive AT-SPI nodes are retained even when a retailer supplies no
accessible name. Such records use the literal `<unlabelled>` marker and expose
role, accessibility state, screen bounds when available, an ephemeral action
locator, and a path-derived `control_id` that stays stable for the current
Firefox generation. This makes otherwise unnamed color/size controls
distinguishable without inventing labels or consulting the DOM; selected,
checked, pressed, and active states remain explicit.

Navigation and click readback now waits for two matching accessibility
snapshots within a bounded interval and returns one of `stable`, `in_flight`,
`terminal_success`, or `terminal_error`. A sparse document-only tree is
`in_flight`, not success. `status=delivered` records input delivery only;
terminal retailer confirmation is a separate deterministic state. Replaying an
`action_key` returns `already_delivered` with `input_sent=false` and performs no
second click. The action intent is persisted before X11 input; an interruption
in that narrow delivery window returns `delivery_uncertain` on replay and also
blocks a second input.

`secure_browser_checkout_readback` extracts only a sanitized commerce record
from visible AT-SPI text: retailer host, caller-supplied safe item nickname,
selected safe color/size labels, quantity, subtotal, shipping, tax, total, and
confirmation state. It never returns raw page text, owner name, email, address,
payment details, or raw order identifiers. The owner-review image path is
separate: `secure_browser_owner_review_capture` writes mode-0600 files outside
the generic evidence directory, pairs each capture with a fresh sanitized
checkout summary, and marks it owner-only/no-vision/no-artifact. Capture fails
closed unless authoritative session context identifies Star in Joy's configured
Telegram owner chat. Star must attach those visible-window captures in that same
chat message as the structured summary. When the review spans viewports, Star
uses bounded `secure_browser_scroll` plus multiple captures; the system does not
fabricate a full-page image.

## Compatibility matrix

| Existing operation | `firefox-ui-v1` behavior | Migration status |
|---|---|---|
| `secure_browser_status` | Reports visible browser, workflows, instrumentation flags, and compatibility version | Preserved |
| `secure_browser_navigate` | Address-bar navigation in the acquired canonical tab plus readback; never creates a tab | Preserved with required acquire |
| `secure_browser_page_snapshot` | Bounded AT-SPI tree with ephemeral `ax:` locators and redacted sensitive control names | Versioned replacement |
| `secure_browser_current_page_summary` | Bounded title, redacted URL, selected tab, count, and visible controls | Preserved |
| `secure_browser_wait_for_stable` | Bounded transition readback with distinct in-flight, stable, terminal-success, and terminal-error states | Added |
| `secure_browser_checkout_readback` | Sanitized structured retailer/item/variant/quantity/subtotal/shipping/tax/total/confirmation fields; no raw checkout text or owner-sensitive data | Added |
| `secure_browser_scroll` | Bounded visible Page Up/Page Down input in the canonical workflow tab plus transition-aware readback | Added |
| `secure_browser_owner_review_capture` | Mode-0600 visible-window capture marked for same-message delivery only to Joy's trusted owner chat; never generic vision/evidence | Added |
| `secure_browser_query` | Returns `FIREFOX_UI_V1_NO_DOM_QUERY`; no JavaScript or DOM result is fabricated | Deliberate incompatibility |
| `secure_browser_click` | Fresh accessibility locator or grounded coordinate, readback, optional action key | Selector mode deliberately incompatible |
| `secure_browser_type` | Bounded non-secret text through X11; response contains character count, not text | Selector mode deliberately incompatible |
| `secure_browser_screenshot` | Visible Firefox window PNG saved mode `0600` under the active Hermes profile | Preserved, viewport only |
| `secure_browser_visual_evidence` | Same visible-window capture with explicit no-full-page note | Versioned replacement |
| `secure_browser_tab_lifecycle` | `acquire`, `status`, `keep_open`, and `release`; old cleanup names map to safe aliases | Versioned replacement |
| `secure_browser_guardrail_check` | Joy-directed UI work allowed; raw profile/session and browser instrumentation blocked | Repurposed boundary description |
| `secure_browser_owner_checkout_review` | Retired compatibility response; ordinary visual evidence/live Kasm view replaces the extra gate | Retired |
| `secure_browser_request_final_purchase_approval` | Retired compatibility response; no redundant platform approval | Retired |
| `secure_browser_execute_final_purchase` | Retired compatibility response; use a fresh locator plus stable action key | Retired |

The `retail_order_*` and `consumable_*` namespaces remain separate from browser
control. The order-refresh runner imports their retained state module directly.

## Star caller and workflow migration

The live Star profile contains one browser-heavy accumulated skill:
`productivity/shopping-assistant`. Its reusable product research, sizing,
retailer, visual inspection, return, and post-purchase knowledge remains useful.
Its CDP/DOM selectors, full-page scripted capture, effect-specific approvals,
owner-review gate, and final-purchase approval choreography are superseded by
the source-managed `star-firefox-ui` skill.

Representative migrated flow:

1. Check `secure_browser_status` for `firefox-ui-v1` and false instrumentation.
2. Acquire one stable workflow tab.
3. Navigate, snapshot, and use fresh `ax:` locators or grounded coordinates.
4. Inspect readback after every input.
5. Use one stable action key for a destructive/financial control and verify the
   visible/retailer result before claiming completion.
6. Keep the same tab open for Joy handoff or release it when complete.
7. Stop on retailer denial, CAPTCHA, login, passkey, 2FA, or other service-owned
   security challenge; never attempt bypass.

Generic desktop-development skills that mention CDP concern Electron/Node
inspection and are not callers of `browser.eyrie`; they are outside this
migration.

## Verification matrix

| Requirement | Automated/source evidence | Live acceptance |
|---|---|---|
| No browser instrumentation | Launcher rejects automation args; KubeCM removes CDP route/ports/args; adapter reports all flags false | Inspect process args and rendered resources |
| Action/readback | Bridge tests assert navigation/click/type readback | Exercise safe fixture pages |
| Same-tab/no duplicates | Repeated navigation test keeps one tab and sends no `ctrl+t` | Long-running navigation/snapshot/click canary |
| Crash/restart recovery | Generation rebind and ambiguous fail-closed tests | Restart bridge and pod against canary profile |
| Ownership/expiry/cap | Agent-created expiry closes once; Joy-owned blank survives; hard cap refuses | Reconcile after forced restart |
| Exactly-once correctness | Duplicate action key suppresses input; key survives failed readback | Non-transactional fixture button counter |
| DOM incompatibility | Adapter tests assert explicit query/selector errors | Star receives versioned result |
| No redundant approval | Adapter tests allow purchase operation and retire three legacy approval endpoints | Fixture cart/checkout/purchase workflow only |
| Profile persistence | PVC unchanged; profile contents never inspected | Canary restart retains visible non-secret state |
| Retailer compatibility | Not inferable from unit tests | Safe pages on multiple sites, especially MSC |
| Egress cause | No explicit proxy env and ordinary NetworkPolicy documented | Compare same-route clean uninstrumented canary; change egress only with grounded evidence |

## Canary, cutover, and rollback

Development must use a clean disposable home/profile, never the production PVC.
Build the Nest Firefox image, launch the image as an isolated owner-visible
canary, and run the automated lifecycle harness plus safe non-purchase retailer
pages. A canary failure cannot modify or delete production state.

Before production rollout, take an opaque volume-level backup/snapshot of the
PVC without mounting or inspecting profile contents. Stop the workload during a
filesystem-level copy if snapshot consistency requires it. Do not attach,
export, log, or source-manage the backup.

Cutover deploys the KubeCM changes and restarts only the Firefox workload plus
the Star/Talon runtime needed to load the adapter. Startup reconciliation must
run before input. Existing production tabs that cannot be proven agent-owned
are never bulk-closed; Joy may close legacy ambiguous tabs visibly once, after
which the new ownership model prevents recurrence. This is the only honest
migration path because the old CDP-era tab metadata cannot prove ownership of
all currently visible tabs.

Rollback restores the prior image/config revision and opaque PVC snapshot. It
must not re-enable CDP as a hidden fallback while claiming `firefox-ui-v1`.
Rollback is a declared return to the prior architecture, not a mixed mode.

## Acceptance interpretation

Phase 1 does not require or request Firefox Sync. Successful source/unit tests do
not prove MSC compatibility. MSC passes only if the safe page renders in the
plain canary; if its security service still denies access, record the visible
outcome and compare legitimate network routes without spoofing or repeated
probing. Production is not complete until Star's actual profile sees the new
skill/tools, the live process has no automation flags, the lifecycle soak keeps
tab count stable across restarts, and intended tabs alone remain visible.

## Phase 1 canary result

An isolated disposable-home pod on `owl` ran the source bridge against the
current Firefox image without mounting the production PVC. The observed Firefox
process had `--no-remote`, `--new-instance`, the canary profile, dimensions, and
the requested page only; it had no Remote Debugging, WebDriver, Marionette,
BiDi, or CDP argument. Every bridge command was a fresh process, exercising
durable state across repeated bridge restarts.

Twenty navigate/snapshot cycles held the local tab count at six before and
after, with no intermediate growth. A safe `Learn more` click returned visible
readback, and replaying its action key returned `already_delivered`. The same
canonical tab then rendered both the MSC Industrial Supply home page and the
Amazon home page. Their visible accessibility trees contained none of the
checked `access denied`, `request rejected`, `security service`, or `captcha`
markers. This result supports browser instrumentation or old browser state as a
contributor to the prior MSC denial on the unchanged route; it does not prove
that egress reputation can never contribute.

`docs/evidence/firefox-ui-canary-example.png` is a deliberately non-sensitive
visual artifact. Pixel inspection confirmed ordinary Firefox chrome and the
rendered Example Domain page, with no error page, credentials, account data, IP
address, or other sensitive content. The extra tabs visible in that disposable
canary came from Firefox/extension onboarding plus isolated test workflows; the
entire canary is deleted after testing rather than migrated to production.
