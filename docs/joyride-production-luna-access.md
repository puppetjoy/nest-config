# Luna production operations access

This is an independent production authority, not an extension of TEST listener
trust. Keep the existing TEST and GitLab grants and resources unchanged.

## Transport and workload boundary

The admitted peer is the existing `tag:luna-gitlab` device at `100.127.2.74`.
Its new exact destination is `172.21.0.3:443`, with TLS SNI and Host
`joyride.eyrie`. The established Luna proxy transport remains in use; no new
browser session, shared owner identity, API token or trusted HTTP header is
required or accepted by the dedicated application listener.

Kestrel must enforce the peer/interface/destination/port tuple before SNAT,
refuse other forwarding and router-local traffic to this VIP, and permit the
matching established reply. The Service retains source identity with local
external traffic policy. Service source ranges, NetworkPolicy and nginx repeat
Kestrel's `172.22.4.3/32` source. This source alone is not proof of peer identity:
the pre-SNAT enforcement and Tailscale provider grant are required parts of the
same boundary.

The non-root TLS proxy mounts only its configuration, TLS certificate and
scratch. Exact trusted operations go only to the new production WSGI listener
on port 8004. Its NetworkPolicy permits only the dedicated proxy, not shared
Contour Envoy. Ordinary owner/browser fallback goes to internal web on port
8003 and retains real session authentication and CSRF. The public root still
goes to web port 8000 through its existing routes; public private-path denials
must remain in place.

## Production capabilities

Allowed capabilities include status/diagnostics/roster/release status,
frontend/content publication, routing and review operations, member read/audit,
external-evidence waiver reset/record, session revocation, provider membership
reconciliation and provider period-end cancellation. The backend binds the
production service principal and records distinct production attribution.

TEST membership simulation, local cancellation, `/ops/deploy`, arbitrary
controller delivery and backend code upload are not capabilities of this path.
Stripe remains authoritative; the service cannot manually grant membership or
fabricate participant legal assent. Do not exercise destructive actions on real
members as engineering acceptance tests.

The graph initializer admits only the fixed immutable graph under explicit
production opt-in, using the production read-only artifact identity mounted at
`/pull` only for that initializer. It verifies size, SHA256, SQLite integrity
and metadata, retains previous immutable graphs and switches selectors
atomically. No TEST drafts, graph-writer credential or TEST identity is copied.

## Delivery and acceptance gates

Pin the exact reviewed backend image containing `trusted_production_wsgi` and
verify packaged source hashes before deployment. Apply the managed workload and
Kestrel firewall/route changes through their existing plans. Provider-side
Tailnet policy must be read freshly and augmented only with the exact new
grant and route approval; do not replace unrelated provider policy with a stale
local file. Owner login/consent remains interactive.

After deployment, verify actual ready workload images, graph identity,
production-only secret consumers, private owner authentication and public
private-path refusal. Positive production access must be tested from the actual
Luna peer through the established transport, paired with denied deployment,
simulation, wrong Host/SNI, malformed raw URI and non-peer controls. A local
fixture or router-local probe is not actual-peer acceptance.

Read-only status and synthetic disposable fixtures establish access and handler
behavior without canceling a real subscription, revoking a real session,
rewriting a real waiver or copying a TEST review into production. Retain exact
operation IDs and server readbacks for any later authorized publication.
