# browser.eyrie secure-browser binding validation — 2026-07-02

This bundle covers the source-managed binding cutover prepared in Kanban task `t_af221521` / Agent Request `^1352`.

The live browser.eyrie end-to-end validation matrix is intentionally not marked complete in this pre-review implementation pass. The change needs Joy/operator review and accepted `merge_deploy_verify` follow-through before the normal Nest/Bolt/KubeCM/Puppet rollout can restart profile services and before Talon/Star can safely rerun the browser.eyrie Firefox workflows against the deployed runtime.

## Safety boundary

- No orders were placed.
- No account, payment, address, cart-setting, or Bitwarden-vault content was inspected or modified.
- No cookies, storage, raw CDP payloads, request headers, raw DOM dumps, or sensitive screenshots were captured into worker-visible artifacts.
- Owner-only checkout evidence paths remain owner-only Telegram delivery paths in the guarded tool code.

## Implementation summary

- `data/kubernetes/app/firefox.yaml` now enables Firefox Remote Debugging on in-cluster service port `9222` for the `browser.eyrie` Firefox/Kasm workload. The port is not exposed by a public CDP ingress.
- Talon and Star profile environments in `data/host/owl.yaml` now set the secure-browser target to `browser.eyrie-firefox`, bind `SECURE_BROWSER_WORKLOAD` to `deployment/firefox`, and define explicit expected/forbidden backend identity guards. Star no longer points `SECURE_BROWSER_CDP_URL` at `https://secure-browser-cdp.eyrie`.
- `files/app/hermes/secure_browser_tool.py` and `files/app/hermes/secure_browser_oauth_tool.py` now default to `deployment/firefox`, report backend identity in status, and fail closed if a browser.eyrie Firefox request is configured for the legacy `deployment/secure-browser`, legacy `secure-browser-cdp.eyrie`, or a live `kasmweb/chrome` workload.
- Documentation now records the browser product split and guarded Firefox Remote Debugging bridge shape.

## Validation results

### 1. Python syntax and built-in smoke tests

Purpose: verify the copied Hermes secure-browser tool modules still import, compile, and pass their built-in policy/sanitization smoke assertions.

Method:

```sh
/opt/hermes-agent/venv/bin/python -m py_compile \
  files/app/hermes/secure_browser_tool.py \
  files/app/hermes/secure_browser_oauth_tool.py
/opt/hermes-agent/venv/bin/python files/app/hermes/secure_browser_tool.py
/opt/hermes-agent/venv/bin/python files/app/hermes/secure_browser_oauth_tool.py
```

Expected: compile succeeds; `secure_browser_tool.py` prints `secure_browser_tool smoke ok`; OAuth helper exits successfully.

Actual: command exited `0`; `secure_browser_tool.py` printed `secure_browser_tool smoke ok`.

Status: PASS.

Artifacts/bindings: local source files only; no browser session or sensitive evidence.

Safety notes: no live browser attachment was attempted.

### 2. Backend identity guard regression probe

Purpose: prove validation fails closed for the exact wrong-target class that invalidated `^1347`: browser.eyrie Firefox validation accidentally using legacy Chrome/Kasm `secure-browser` / `secure-browser-cdp.eyrie`.

Method: loaded `secure_browser_tool.py` three times with controlled environment and fake `kubectl` output:

- configured `SECURE_BROWSER_CDP_URL=https://secure-browser-cdp.eyrie`
- configured `SECURE_BROWSER_WORKLOAD=deployment/firefox` with fake live image `docker.io/kasmweb/firefox:1.18.0`
- configured `SECURE_BROWSER_WORKLOAD=deployment/secure-browser` with fake live image `docker.io/kasmweb/chrome:1.18.0`

Expected: legacy CDP URL and legacy secure-browser workload fail; Firefox workload passes.

Actual:

```json
{
  "chrome": "configured workload matches forbidden legacy secure-browser workload",
  "firefox": "backend identity matches requested browser.eyrie Firefox target",
  "legacy_url": "configured CDP endpoint points at legacy secure-browser ingress"
}
```

Status: PASS.

Artifacts/bindings: fake `kubectl` output only; no live cluster mutation.

Safety notes: no live browser attachment was attempted.

### 3. Nest/Puppet static validation

Purpose: verify the Nest config module still passes repository validation after Hiera, KubeCM app data, copied Hermes tool, and docs edits.

Method:

```sh
pdk validate
```

Expected: validator exits `0`.

Actual: exited `0`; PDK reported `Running all available validators...`.

Status: PASS.

Artifacts/bindings: repository validation output only.

Safety notes: no live deployment.

### 4. KubeCM/Bolt render-path smoke

Purpose: verify the Firefox deployment plan can load its KubeCM dependency and execute the render code path without applying to the cluster.

Method:

```sh
bolt module install
bolt plan run nest::eyrie::ai::deploy_firefox deploy=true render_to=/tmp/t_af221521-firefox-render.yaml
```

Expected: dependencies resolve; plan runs the `helm template` render path rather than deploy/apply.

Actual: first render attempt failed because `kubecm::deploy` was not installed in `.modules`; after `bolt module install`, the plan completed successfully with `Render firefox from Helm chart ... with 0 failures`. The requested `/tmp/t_af221521-firefox-render.yaml` was not visible afterward in this terminal session, so this is recorded as a plan/render-path smoke only, not as an attached rendered-manifest artifact.

Status: PASS with artifact caveat.

Artifacts/bindings: Bolt stdout/stderr in task run history; no rendered file attached.

Safety notes: `render_to` path was used; no `helm upgrade --install` deployment was requested.

## Live browser.eyrie validation matrix for accepted follow-through

These rows remain pending until Joy/operator accepts the implementation review and authorizes `merge_deploy_verify` follow-through.

| Test name | Purpose | Method | Expected | Actual | Status | Artifacts/bindings | Safety notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Deployment/reachability | Prove `ai/firefox` is the target and `browser.eyrie` is reachable | After deploy, inspect `kubectl -n ai get deploy,svc,httpproxy firefox` and browse `https://browser.eyrie/` | `deployment/firefox`, `kasmweb/firefox:1.18.0`, ready pod, reachable Kasm UI | Pending accepted deploy | PENDING | kubectl summaries; sanitized browser status | No secrets |
| Persistent Firefox/Kasm bridge attach | Prove `secure_browser_*` attaches to Firefox, not Chrome | Run `secure_browser_status`, `current_page_summary`, and backend identity readback | backend identity ok; workload `deployment/firefox`; no `secure-browser-cdp.eyrie` | Pending accepted deploy | PENDING | sanitized status JSON | No raw CDP URL in report |
| Public/private navigation | Verify bounded navigation | Navigate safe public page and safe Eyrie page; snapshot sanitized text | navigation ok or safe refusal with reason | Pending accepted deploy | PENDING | sanitized snapshots only | No login/security pages |
| Amazon safe browsing/order history | Verify logged-in Amazon safe browsing/order-history sanitization | Navigate product/order-history safe routes; collect sanitized summaries only | no raw order numbers/address/payment; human takeover for login/security | Pending accepted deploy | PENDING | safe summaries/bindings | No order modifications |
| Bitwarden presence | Prove Joy takeover surface, not vault access | Observe extension presence from safe visible UI metadata only | presence noted without vault content | Pending accepted deploy | PENDING | redacted summary | Do not inspect vault contents |
| Read-only query and mutation rejection | Verify query guard | Run benign query and rejected mutating query | benign ok; click/fetch/storage mutation rejected | Pending accepted deploy | PENDING | sanitized query results/errors | No storage/cookie output |
| Safe click/type | Verify allowlisted UI interactions | Use a non-sensitive field/control on a safe page | allowed effects only; final purchase/login/account controls refused | Pending accepted deploy | PENDING | sanitized action result | No account/payment/address/cart settings |
| Sensitive screenshot boundary | Verify screenshot refusal/redaction/owner-only route | Try safe screenshot and sensitive-page screenshot/owner-review paths | safe screenshot ok; login/account/payment refused or owner-only; no worker-visible sensitive PNG | Pending accepted deploy | PENDING | safe PNG paths or owner-only binding ack | No sensitive screenshots attached |
| Owner-only checkout review binding | Verify material binding without exposing evidence | On a safe mock or supervised checkout-prep state, request owner-only review binding | binding returned, owner-only delivery ack, no raw evidence to worker | Pending accepted deploy | PENDING | binding ids only | No Place Order |
| Final purchase negative paths | Verify hard final-purchase gates | Try ordinary final purchase guard/executor without approval or ambiguous controls | refusal; no purchase | Pending accepted deploy | PENDING | sanitized refusal result | Do not place orders |
| Audit log safety | Verify high-level audit only | Inspect audit entries generated by safe actions | high-level actions only; no cookies/storage/raw DOM/headers | Pending accepted deploy | PENDING | sanitized audit excerpts | No secret log material |
| Persistence/reconnect semantics | Verify persistent visible Firefox session survives reconnect | Record safe page, restart/reconnect as approved, reread summary | state persists or documented safe reset behavior | Pending accepted deploy | PENDING | sanitized summaries | No credential prompts handled by agent |
