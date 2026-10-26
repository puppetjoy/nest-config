# Luna's isolated Joyride TEST access

Existing exact release/status and member routes use Tailscale authentication only.
The former stored-token Muse connector and member scope list are retired and
disconnected, not active registration metadata. Luna needs no bearer, new Muse
connector credential, synthetic identity header, secret bridge or routine ops CI
job. Existing CI preview credentials and ordinary application
member/admin authentication remain unchanged. Production and public launch are
outside this TEST change.

## Exact trust boundary

- Existing Muse device `nQjHi2NSXC11CNTRL`, address `100.127.2.74`, has the
  administrator-owned `tag:luna-gitlab`. Do not assign it to another device.
- Existing GitLab destination remains `172.21.2.1/32`, TCP 22 only.
- TEST destination remains `172.21.1.3/32`, TCP 443 only, through Kestrel's
  existing `tag:kestrel-gitlab-router` subnet router. No grant is broadened.
- No shared ingress, whole subnet, DNS, default route, Tailscale SSH or route
  auto-approval. Preserve OpenVPN, DNS/DHCP, BIRD and management services.

Tailscale authenticates the peer before decrypted traffic enters `tailscale0`.
The independent `inet nest_luna` forward guard accepts TEST traffic only from
that interface AND exact Luna IPv4 source AND exact destination/port. A subsequent
unconditional TEST-destination drop rejects all other forwarded sources before
SNAT, even if a later shared firewall rule would accept them. The output guard
also drops router-local connections to the TEST VIP: Kestrel's own processes do
not inherit Luna's trust. GitLab forwarding and established replies are retained.

Firewalld performs only the existing bounded subnet SNAT. The verified BIRD
route sends TEST traffic via Falcon; the downstream source is `172.22.4.3`.
That address is NOT independently a Tailscale identity: the pre-SNAT interface,
peer source and local-output guards are mandatory prerequisites. Recheck their
installed bytes and effective rules before enabling token-free app routing.
The router, Kubernetes nodes and network control plane remain privileged trust
roots; this does not defend against an administrator replacing their rules or
forging traffic from a compromised network control plane.

The source-preserving Local LoadBalancer accepts only `172.22.4.3/32`. Ingress
NetworkPolicy repeats that source restriction. Only the stateless nginx listener
runs on a workstation node matching the TEST MetalLB advertisement. App/database
retain ordinary worker scheduling. Nginx has no service-account token, application
secret, database or media mount. It runs nonroot, read-only, with dropped
capabilities and bounded tmpfs. Access logs are disabled.

## Isolated application listener

`joyride-test-access` terminates TLS with the managed TEST certificate. Unknown
SNI fails TLS; wrong Host returns 421. Fixed upstreams cannot be chosen from
caller headers or URLs. Public/member requests retain ordinary authentication.
Only these exact raw method/path pairs, with no normalized variants,
reach the separate `joyride.trusted_test_wsgi:application` process on port 8002:

- `GET /ops/status`: sanitized TEST-only deployment status.
- `GET /ops/diagnostics`: sanitized queue counts/timestamp, not raw logs/payloads.
- `POST /ops/deploy`: bounded JSON, independently verified digest, TEST only,
  promote/rollback with existing idempotency and audit checks.

All caller headers are discarded on these ops upstream requests; only the fixed
Host, connection handling and JSON content type for deployment are supplied.
There is no injected credential or trusted identity header. Ops requests have
bounded bodies, deadlines, connection concurrency and request rate. Responses
remain the bounded application schema. Roster, controller, admin and production
authority are absent; only the exact TEST member operations below are added.
An HTTP 202 is queue
acceptance, not succeeded delivery.

Only the exact private-access pod selector may connect to port 8002. Neither
shared ingress nor the TEST deployment adapter is allowed that port; their
8000/8001 access remains unchanged. Private access has no port 8001 permission.
The ordinary ops Service still requires its
existing bearer credentials; the public listener exposes no ops routes. Other
cluster pods and direct PodIP/Service calls must fail network admission. Inspect
all additive NetworkPolicies, not merely the named policy. Kubernetes node-local
and same-pod processes are privileged trust roots, not untrusted network clients.

### Trusted TEST routing

The same admitted backchannel now forwards exactly `GET /routing/status` and
`POST /routing/propose`, `/routing/match`, `/routing/settle`, `/routing/export`
to trusted port 8002 only. No query strings, trailing slashes, normalized or
encoded target variants, unknown operations or other methods are accepted.
All caller headers are discarded except the supplied content type; no identity,
cookie, bearer or synthetic trust header reaches the application. POST content
must be JSON, capped at 1 MiB; upstream read/send budgets are 120 seconds.
No tailnet grant, VIP, NetworkPolicy, domain, token or production authority is
added. The graph remains private and read-only. Parent-owned Luna backchannel
and final route acceptance remain separate from engineering endpoint checks.

### Trusted TEST member administration

The raw method/path allowance reaches only port 8002:

- `GET /ops/members/<email>`
- `GET /ops/members/<email>/audit`
- `POST /ops/members/<email>/waiver/reset`
- `POST /ops/members/<email>/waiver/record`
- `POST /ops/members/<email>/subscription/cancel`
- `POST /ops/members/<email>/membership/set`
- `POST /ops/members/<email>/sessions/revoke`

Only audit admits single-valued `before` (UUID) and `history_before` (integer)
cursors, in either order. Other queries, unknown routes, wrong verbs, traversal,
nested escapes and normalized route variants fail closed. Printable ASCII email
escapes such as `%40` and `%2B` retain their original upstream encoding; separators,
percent, controls and query delimiters cannot be escaped into email authority.
The proxy preserves only `Idempotency-Key` and `Content-Type`, discarding
Authorization, cookies and every caller identity claim. Bodies remain bounded to
8 KiB with the existing TLS, rate, connection and timeout limits. Private-access
ingress/egress permission for 8001 is removed; no public ingress or tailnet grant
is added. Status, diagnostics and releases retain their existing contracts.

Legacy TEST bearer services/scopes remain distinct and unchanged on port 8001;
they are not Luna's delivered interface. Production is unchanged. Trusted
mutations require an `Idempotency-Key` and record the actual service principal
`trusted-test:tailscale-backchannel`, never a named person or `ops:<HMAC>` token
actor. Transactional replay/conflicts remain scoped to actor plus key, target,
operation and payload. All member endpoints independently enforce TEST environment.
The application contract in Joyride `docs/test-member-administration.md` defines
payloads, atomic audit/replay, historical waiver retention and session epochs.
Public/internal web do not register member ops routes. Engineering verification
uses a nonexistent synthetic member, never real account mutations. Parent-owned
Luna acceptance separately performs only Joy's explicitly authorized TEST
read/reset/readback/audit sequence; synthetic checks do not claim that delivery.

Deploy the authoritative merged-main image to every application listener and
worker before exposing the new private route. After waiver reset or session
revocation, an old-image rollback is unsafe; use separately reviewed compatible
forward repair, never reverse migration 0009 or delete legal/audit history.

The immutable baseline application must include the trusted entry point. Older
artifacts predating application MR 3 cannot be used as successful rollback
candidates with this workload shape. Reverting the architecture requires an
explicit reviewed Nest rollback, disabling private ops routing first, not an
authentication bypass. The TEST adapter validates all four named app containers
and both initializers, preserving exact workload identity and interruption recovery. This ordinary
self-service path does not require signed installed evidence or owner receipts.

## Managed deployment and acceptance

1. Require exact-head CI, including real pinned-nginx and controller fixtures.
   Render through the normal declarative wrapper:

       bolt plan run nest::eyrie::deploy_joyride_test render_to=/modules/nest/.local/joyride/access-rendered.yaml

   Rendered manifests contain Secrets: keep restricted, never attach or print.
   Perform a Kubernetes server-side dry run.
2. Merge reviewed source. Deploy Puppet code through `nest::puppet::deploy`.
   Review Kestrel's scoped noop and apply only `luna_gitlab` and `firewalld` via
   `nest::puppet::run`; inspect shared changes and repeat for no drift. Read back
   exact installed guard bytes/rules, preferences, BIRD route and peer identity.
   No direct SSH or manual host Puppet deployment fallback.
3. Before starting the trusted listener, prove router-local and non-Tailscale
   paths cannot reach the VIP, source-preserving Service/policy confinement and
   the exact existing Tailscale grant/route. Do not broaden grants for tests.
   Then deploy TEST only with `nest::eyrie::deploy_joyride_test` and inspect
   Service endpoints, all additive policies, ready images and normal TLS.
4. Use only the existing dedicated Joyride side chat. Luna connects via existing
   proxy 3130 to `172.21.1.3:443`, SNI/Host `joyride-test.eyrie`, with the public
   Eyrie CA as a request-scoped anchor and hostname checking. No `-k`, new client,
   connector secret, main chat, direct Muse API or broad network permission.
5. Verify token-free status/diagnostics and an authorized verified-artifact TEST
   deployment through Luna's actual connection. Independently inspect succeeded
   application state and exact runtime digest. Check wrong methods/paths,
   production, roster, admin, controller, spoofed headers and direct-origin denial.
   Retain GitLab SSH and member authentication. Ordinary LAN/shared ingress must
   still deny equivalent token-free access. Record unavailable live negative
   clients explicitly; policy inspection alone is not an exercised client.

Fixture checks (local fixtures are not live network/application acceptance):

    python3 spec/app/joyride/test_private_access.py

    sudo unshare --net nft --check --file files/tailscale/luna-gitlab.nft

## Rollback and remaining work

Disable private ops routing before relaxing any router or pod isolation. Revoke
only the TEST grant/route if access must be removed; preserve GitLab. Do not
reset the router/device, alter keys/expiry or restart Firefox without approval.
Deleting Kubernetes resources remains separately destructive. All production,
payment, mail, business-content and publication gates remain unchanged. This
runbook describes source and required acceptance, not a claim of live success.
