---
name: star-firefox-ui
summary: Use when Joy directs a browser workflow in persistent browser.eyrie Firefox.
description: Operate Joy's persistent Firefox through accessibility locators, visual readback, and one canonical workflow tab without browser-internal automation or redundant approval gates.
---

# Star persistent Firefox UI workflow

This is the current browser.eyrie contract and supersedes older shopping-assistant references that describe CDP/DOM selectors, mandatory per-operation effect approvals, owner-checkout-review approval gates, trusted final-purchase approval requests, Firefox Sync, or full-page DOM capture.

## Authority and secrets

- Joy's direction to Star for the workflow is the authorization boundary. Do not add platform approval prompts for navigation, clicks, forms, account work, cart/checkout, or purchase actions inside that directed workflow.
- Preserve exact-current intent: if material item, quantity, variant, seller, price, shipping, subscription, or total changes, ask Joy rather than guessing.
- Never pass passwords, passkeys, 2FA/CAPTCHA values, card/account numbers, tokens, recovery codes, or other secrets as `secure_browser_type` text. Use visible Firefox/Bitwarden UI; Joy participates only when the site itself requires owner authentication or a security challenge.
- Never inspect or request cookies, storage, request headers, Firefox profile files, Sync material, or browser-debugging endpoints.

## Canonical flow

1. Call `secure_browser_status`; require `protocol=firefox-ui-v1` and all instrumentation flags false.
2. Call `secure_browser_tab_lifecycle(action='acquire', workflow_id=<stable id>)` once. Reuse that same workflow id throughout.
3. Navigate with `secure_browser_navigate`. It reuses the canonical handoff tab and never creates a tab implicitly.
4. Read with `secure_browser_page_snapshot` or `secure_browser_current_page_summary`. Locators are ephemeral: refresh immediately before every interaction.
5. Click with a fresh `ax:...` accessibility locator or a grounded visible coordinate. CSS selectors are deliberately unsupported. Every mutation returns visual/accessibility readback; inspect it before continuing.
6. Type only non-secret text with a fresh accessibility locator. The result reports only character count and redacted readback.
7. For destructive or financial controls, set a stable `action_key` derived from the directed workflow step. Reusing it returns `already_delivered`; this is exactly-once correctness, not a user-approval gate.
8. Use `secure_browser_visual_evidence` for the visible window. There is no fabricated full-document capture or script-derived crop.
9. Keep a handoff open with `secure_browser_tab_lifecycle(action='keep_open', lease_seconds=...)`; release it when done. Cleanup closes only confidently agent-created tabs. Ambiguous or Joy-owned tabs are preserved.

## Compatibility changes

- `secure_browser_query`: returns `FIREFOX_UI_V1_NO_DOM_QUERY`; replace it with accessibility snapshots, page summaries, and visual evidence.
- `selector=` on click/type: returns `FIREFOX_UI_V1_NO_CSS_SELECTORS`; refresh and use the supplied accessibility locator.
- `approved_effect`: accepted only as a legacy audit label; it does not create an approval gate.
- `secure_browser_owner_checkout_review`, `secure_browser_request_final_purchase_approval`, and `secure_browser_execute_final_purchase`: retired compatibility endpoints. Use ordinary evidence and direct `secure_browser_click` with a stable `action_key` after Joy directs the workflow.
- Older `shopping_browser_*` names and retailer-specific helper APIs are historical. Use the `secure_browser_*` Firefox UI surface.

## Retailer security friction

If a retailer displays a security-service denial, connection-verification page, CAPTCHA, or bot block, stop repeated probes. Preserve the same tab, report the visible result, and route a sanitized Talon issue. Do not spoof fingerprints, rotate/disguise origin, bypass CAPTCHA, or infer whether instrumentation versus egress caused the block without comparative evidence.
