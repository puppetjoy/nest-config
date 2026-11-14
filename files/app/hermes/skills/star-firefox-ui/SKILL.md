---
name: star-firefox-ui
summary: Use when Joy directs a browser workflow in persistent browser.eyrie Firefox.
description: Use when Joy directs Firefox work. Preserve scoped windows.
---

# Star persistent Firefox UI workflow

This managed skill describes `firefox-windows-v3`: one persistent Firefox
profile and login session, with a separate native window bound to each request.
It supersedes legacy AX-only, global-tab and no-instrumentation descriptions;
it does not add purchase approval gates.

## Authority and secrets

- Joy's direction to Star for the workflow is the authorization boundary. Do not add platform approval prompts for navigation, clicks, forms, account work, cart/checkout, or purchase actions inside that directed workflow.
- Preserve exact-current intent: if material item, quantity, variant, seller, price, shipping, subscription, or total changes, ask Joy rather than guessing.
- Never pass passwords, passkeys, 2FA/CAPTCHA values, card/account numbers, tokens, recovery codes, or other secrets as `secure_browser_type` text. Use visible Firefox/Bitwarden UI; Joy participates only when the site itself requires owner authentication or a security challenge.
- Never inspect or request cookies, storage, request headers, Firefox profile files, Sync material, or browser-debugging endpoints.

## Canonical flow

1. Inspect `secure_browser_status`; it is nonallocating and not proof that an action succeeded.
2. V3 keeps one Firefox process/profile/login session and separates each authoritative Kanban task into its own immutable window binding. The pre-existing owner window is preserved. Dispatcher task scope selects the window; `workflow_id` and tool `task_id` do not override scope.
3. `secure_browser_page_snapshot` may allocate before observing. Lifecycle `status` and `recover` are nonallocating. Acquire or inspect the binding using `secure_browser_tab_lifecycle`, then navigate with `secure_browser_navigate`.
4. V3 click/type use CSS selectors or viewport coordinates in the bound window. Legacy accessibility locators are refused. Ground interactions in fresh visible page evidence. The query surface is bounded and does not allow arbitrary JavaScript, profile/session access, global screenshots, or global input.
5. Keep Joy-directed workflow authority intact; do not insert redundant purchase approval gates. Never pass secrets as tool text.
6. Preserve the stable action key. If native navigation/input is uncertain, do not replay or mint a new key. Status/readback use the same native transport and are not independent transport confirmations.
7. Reconcile only with bounded read-only status/recovery. Preserve windows, journals, and unknown creation provenance. Do not treat status as success, close/replace ambiguous windows, or tell Star to restart; unresolved state routes to engineering repair.
8. Keep a needed task handoff open with `secure_browser_tab_lifecycle(action='keep_open', lease_seconds=...)`, using an explicit bounded lease. Release only the confidently owned task window when finished; never close the owner window or an unknown creation. A closed task scope cannot be reopened by changing `workflow_id`.

## Supported observation and interaction

- Read current content through `secure_browser_page_snapshot` and `secure_browser_current_page_summary`. Both use the same native snapshot path; a summary is not an independent transport. Snapshot-derived node descriptions are observations, not legacy AX input locators.
- Use a fresh, unique rendered CSS selector or a screenshot-grounded viewport coordinate for click/type. V3 refuses legacy AX locators. The viewport, occlusion, protected-field, generation and ownership guards still apply. All native input needs a stable `action_key`; the key prevents replay, not a purchase approval ceremony. `mode='insert'` preserves existing text; request `mode='replace'` explicitly for replacing an ordinary field.
- `secure_browser_query` accepts only documented read expressions, for example `document.title`, `location.origin`, `document.domSnapshot` and `document.readText("pre",0)`. It is not arbitrary JavaScript. For text, pass `nextCursor` unchanged with the same expression until `complete=true`; changed-page cursors fail closed. Never read profile, cookie, storage or secret values.
- V3 screenshots and visual evidence capture the bound rendered page viewport, not native chrome, a full document or the global desktop. Do not work around this boundary with another browser/session.
- On `FIREFOX_NATIVE_OUTCOME_UNCERTAIN` or `FIREFOX_CREATION_UNCERTAIN`, retain the original outcome and action key. The adapter can include one finite recovery read; inspect its result instead of automatically repeating navigation, input or recovery. A verified binding alone does not prove page or purchase completion. If bounded readback remains unavailable, preserve the binding and route the sanitized error to Talon; do not allocate a replacement request/window or clear history.

## Checkout verification and owner review

- Before presenting final purchase options, call `secure_browser_wait_for_stable`, then `secure_browser_checkout_readback` with a safe item nickname. Treat `in_flight`, `terminal_success`, and `terminal_error` as distinct states; a delivered click is never confirmation by itself.
- Present the structured retailer, item nickname, variant, quantity, subtotal, shipping, tax, total, and confirmation status exactly as returned. A null structured field means that parser did not extract it, not that the page cannot be read: inspect ordinary accessible page text/values and visible evidence separately, clearly distinguishing observed content from structured extraction.
- In that same Telegram message, attach at least one `secure_browser_owner_review_capture` image of the final pre-purchase retailer review. Pass the same safe item nickname; the capture result pairs the image with another sanitized `checkout_summary`, which must agree with the text you send. If the review spans viewports, capture the current viewport, use `secure_browser_scroll`, capture each additional visible viewport, and attach all captures together without fabricating a full-page image.
- Owner-review captures may contain masked payment/account or address context. Deliver them only to Joy's trusted owner chat. Never send them through generic vision/OCR, logs, evidence artifacts, task attachments, Talon notifications, or any other recipient. Do not describe or transcribe sensitive screenshot content into tool text.
- The structured summary and owner-only captures are complementary and must appear together; neither substitutes for the other. These are review evidence, not an extra approval ceremony.

## Compatibility changes

- V3 query is a bounded allowlist, not arbitrary JavaScript or profile/secret access.
- V3 uses CSS selectors and viewport coordinates; legacy AX locators are refused.
- `approved_effect`: accepted only as a legacy audit label; it does not create an approval gate.
- `secure_browser_owner_checkout_review`, `secure_browser_request_final_purchase_approval`, and `secure_browser_execute_final_purchase`: retired compatibility endpoints. Use ordinary evidence and direct `secure_browser_click` with a stable `action_key` after Joy directs the workflow.
- Older `shopping_browser_*` names and retailer-specific helper APIs are historical. Use the `secure_browser_*` Firefox UI surface.

## Retailer security friction

If a retailer displays a security-service denial, connection-verification page, CAPTCHA, or bot block, stop repeated probes. Preserve the same tab, report the visible result, and route a sanitized Talon issue. Do not spoof fingerprints, rotate/disguise origin, bypass CAPTCHA, or infer whether instrumentation versus egress caused the block without comparative evidence.
