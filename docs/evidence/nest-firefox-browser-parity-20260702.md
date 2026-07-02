# browser.eyrie Nest Firefox parity validation — 2026-07-02

Task: `t_7a68ae00` / Agent Request `^1367`.

## Safety boundary

- No orders were placed.
- No account, payment, address, cart-setting, or Bitwarden vault content was inspected or modified.
- No cookies, local storage, raw CDP payloads, request headers, raw DOM dumps, raw order numbers, full address/payment/account details, or sensitive screenshots were captured into this worker-visible artifact.
- The Amazon order-history / owner-only post-purchase rows were not completed because the live persistent profile currently lands on Amazon Sign-In and Joy/Bitwarden takeover is required before those rows can be rerun safely.

## Source and rollout summary

- Nest config `origin/main` is at `d2ef5c09`.
- `browser.eyrie` now uses `registry.gitlab.joyfullee.me/nest/tools/firefox:latest` with `imagePullPolicy: Always`.
- The live Firefox pod image is `registry.gitlab.joyfullee.me/nest/tools/firefox@sha256:8fa99968a238cd61bf0fa92fc9a943d26038c2d8a4d99d5b2914a1489143a5e3`.
- The live Camofox deployment uses `registry.gitlab.joyfullee.me/nest/tools/camofox:latest` with `imagePullPolicy: Always`.
- Puppet code deploy succeeded to legacy/test/prod OpenVox and owl applied catalog version `d2ef5c09` with 0 failures.

## Findings fixed during validation

1. Firefox BiDi could attach but navigation failed because Portage Firefox content processes crashed under the unavailable container user-namespace sandbox. The wrapper now disables Firefox process sandboxes inside the pod while preserving the Kubernetes, NetworkPolicy, backend identity, sanitization, and final-purchase boundaries.
2. Firefox initially still showed `SEC_ERROR_UNKNOWN_ISSUER` for `browser.eyrie` because `www-client/firefox` overwrote `libnssckbi.so` after the base cert class linked it to p11-kit trust. The tool class now orders Firefox before `nest::base::certs`; the live image has `/usr/lib64/libnssckbi.so -> /usr/lib64/pkcs11/p11-kit-trust.so`.
3. The root HTTPProxy redirect pointed at `/index.html`, but Gentoo `www-apps/novnc` provides `vnc.html`. The root redirect now lands on `/vnc.html` and `curl -ksSL https://browser.eyrie/` returns `200 https://browser.eyrie/vnc.html` with `<title>noVNC`.
4. The wrapper preserved runtime `HOME=/root`, putting Firefox state on ephemeral root storage instead of the mounted PVC. It now defaults `HOME` to `/home/kasm-user` unless `FIREFOX_HOME` is explicitly set; the live pod creates the profile under `/home/kasm-user/.mozilla/firefox/nest-secure-browser`.

## Validation matrix

| Test name | Purpose | Method | Expected | Actual | Status | Artifacts/bindings | Safety notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Static validation | Verify source syntax/lint | `sh -n files/firefox-browser/nest-firefox-browser.sh`; `pdk validate`; `git diff --check` | All pass | All passed before each commit | PASS | task run output | No live browser access |
| Build and publish Firefox image | Build Nest-owned Portage Firefox/noVNC image | `./bin/build firefox zen5 emerge_default_opts="--jobs=4 --load-average=12" makeopts="-j8" deploy=true` | Build, smoke test, commit, and registry push succeed | Build applied catalog, smoke-tested Firefox 140.9.0esr, committed image config `1a64d79e...`, and pushed `registry.gitlab.joyfullee.me/nest/tools/firefox:latest` | PASS | task run output | No browser secrets in image |
| Puppet code deploy | Deploy source to legacy/test/prod Puppet/OpenVox and owl | `./bin/bolt-wrapper plan run nest::puppet::deploy --stream`; `./bin/bolt-wrapper plan run nest::puppet::run targets=owl --stream` | Code servers and owl converge to latest commit | legacy/test/prod verified `d2ef5c09`; owl applied `d2ef5c09` with 0 failures | PASS | task run output | Inventory-backed Bolt path |
| KubeCM Firefox deploy | Deploy browser.eyrie app from source | `./bin/bolt-wrapper plan run nest::eyrie::ai::deploy_firefox --stream`; `kubectl rollout status deploy/firefox` | Helm upgrade succeeds and pod ready | Helm revision 10 deployed; deployment ready 1/1 | PASS | task run output | Source-managed KubeCM path |
| Deployment identity | Prove secure browser binds to Nest Firefox workload | `secure_browser_status`; `kubectl -n ai get deploy/firefox` | `deployment/firefox`, `nest/tools/firefox`, backend identity ok | `backend_identity.ok=true`, expected image regex `nest/tools/firefox`, workload `deployment/firefox`, ready replicas 1/1 | PASS | secure_browser_status result | No raw CDP URL returned |
| Camofox font-bearing image | Verify Camofox remains on Nest image with font support | `kubectl -n ai get deploy/camofox`; prior build/deploy evidence in task run | Camofox on Nest image and ready | `deployment/camofox` ready 1/1, image `registry.gitlab.joyfullee.me/nest/tools/camofox:latest`, pull policy Always | PASS | task run output | No browser secrets |
| Firefox fonts and trust | Verify Nest fonts and Eyrie trust in image | `fc-match "Noto Color Emoji"`; `ls -l /usr/lib64/libnssckbi.so`; `curl -ksSL https://browser.eyrie/` inside pod | Emoji/font available, NSS trust linked to p11-kit, browser.eyrie certificate trusted | Noto Color Emoji resolved; `libnssckbi.so` symlinked to p11-kit; `curl` returned `200 https://browser.eyrie/vnc.html` and title `noVNC` | PASS | task run output | No sensitive pages |
| Public secure-browser navigation | Verify bridge can navigate/snapshot/query/screenshot on public page | `secure_browser_navigate('https://example.com/')`; `page_snapshot`; `query`; `screenshot` | Navigation ok and sanitized outputs | Example Domain navigation, snapshot, query, and screenshot succeeded | PASS | safe screenshot `/home/joy/.hermes/profiles/star/secure-browser-screenshots/secure-browser-20260702T081756Z-3526628.png` | Public page only |
| Browser.eyrie noVNC reachability | Verify Joy-visible operator URL reaches noVNC | `curl -ksSL -w ... https://browser.eyrie/` | 200 noVNC page, no cert caveat | `200 https://browser.eyrie/vnc.html`, `<title>noVNC` | PASS | task run output | No VNC screenshot captured |
| Amazon safe browsing/search | Verify ordinary safe browsing and non-sensitive interactions | `secure_browser_navigate('https://www.amazon.com/')`; sanitized snapshot; type `coffee filters`; click search | Sanitized home/search; no cart/account/payment mutation | Home and search loaded; address fragments redacted; safe type/click succeeded; result snapshot sanitized | PASS | task run output | No add-to-cart, checkout, account, payment, or address edits |
| Amazon order-history sanitization | Rerun baseline order-history row after cutover | Navigate to `https://www.amazon.com/gp/css/order-history`; current summary/snapshot/query | Sanitized order-history proof summary if logged in; otherwise safe takeover boundary | Current persistent profile lands on `Amazon Sign-In`; ordinary outputs are sanitized login-page text only | BLOCKED for Joy takeover | task run output | Do not enter credentials/Bitwarden as worker |
| Owner-only post-purchase visual proof | Rerun owner-only proof binding row | `secure_browser_owner_checkout_review` only after a real order-history/post-purchase page is visible | Joy-only Telegram evidence; worker receives binding only | Not run because the browser is at Amazon Sign-In and Joy/Bitwarden takeover is required first | BLOCKED for Joy takeover | none | Avoid sensitive screenshot/login handling |
| Final purchase negative gate | Verify final purchase remains blocked | `secure_browser_guardrail_check(operation='place_order')` | Ordinary tool use denied; trusted approval required | `allowed=false`, `trusted_approval_required=true` | PASS | tool result | No checkout/final purchase page used |

## Current blocker

The source-managed cutover itself is live and the non-sensitive parity rows pass. The only remaining baseline rows are the Amazon order-history / owner-only post-purchase proof rows, which require Joy to log in or restore Bitwarden/session state in the visible browser. I did not inspect or handle credentials, Bitwarden, account state, payment/address data, or sensitive screenshots.
