# Pattern Kit on Eyrie

`https://patternkit.eyrie` is the canonical daily Pattern Kit Studio entrypoint.
It runs the accepted Pattern Kit and Atelier revisions from dedicated host-mounted
development checkouts on owl, persists collaborative sessions on an `owl-crypt`
PVC, and restarts automatically when watched source files change.

The source status bar above Studio shows each checkout's branch, abbreviated
revision, and dirty state. The machine-readable equivalent is
`/__patternkit/status`. The deployment refuses to start when either checkout is
not at the source-managed compatible revision tuple.

Both user-facing endpoints use the `Pattern Kit Eyrie` public GitLab OAuth/PKCE
application. The in-pod proxy strips caller-supplied identity headers and passes
only the authenticated GitLab username to Studio. The pod has no Git private
key, token, credential helper, or registry credential mounted into either source
checkout.

Any account accepted by the private GitLab instance is authorized; there is no
second Pattern Kit-specific user or group allowlist.

## Workbench isolation

`https://patternkit-workbench.eyrie` is a supplementary persistent Firefox/Kasm
workbench. It has its own Deployment, PVC, browser profile, OAuth session, bridge
state, labels, and Service. It does not mount or reuse the `browser.eyrie` PVC,
Bitwarden policy, tabs, cookies, CDP ingress, or secure-browser transient target
file. A dedicated hostname-aware CONNECT proxy permits the workbench browser to
reach only `patternkit.eyrie` and the GitLab OAuth origin. Kubernetes egress
policy permits the browser pod to reach only DNS and that proxy, so the shared
compute ingress VIP cannot be used to bypass the hostname boundary and attach to
`browser.eyrie`.

A fresh or restarted workbench opens a local page with one visible action:
`Open and share Pattern Kit Studio`. That action creates a nonce in the visible
Pattern Kit URL and records the active Firefox target ID plus browser process
generation before redirecting that same tab. The private bridge reports a binding
only while the exact target remains active, its URL contains that nonce, and the
browser generation still matches. A browser restart, tab switch, origin change,
or stale context therefore fails closed as `explicit-share-required`; URL order
and last nonblank context are never accepted as proof.

The bridge is cluster-private on `service/patternkit-workbench:8766`. Its visible
landing and share action are loopback-only, while remote status requires a
constant-time checked bearer from the Pattern Kit secret. Phase ^1553 may
consume that compact binding status but must keep the credential and service
behind the Star profile's dedicated Pattern Kit tool boundary.

## Deployment and verification

From the Nest config project root:

First update owl's existing development checkouts over their authenticated host
Git remotes. Require clean trees and use fetch plus fast-forward-only checkout;
the pods intentionally have no Git credentials and will fail their revision init
gate rather than update source themselves. Confirm Pattern Kit is at
`2717eca2ea84863d2cafb179dcc74e097b9829cd` and Atelier is at
`986befb94bc941fcaeebdd3e35d28b96453888bd` before applying the workload.

```sh
./bin/bolt-wrapper plan run nest::puppet::deploy --stream
./bin/bolt-wrapper plan run nest::eyrie::ai::deploy_patternkit --stream
```

The suspended `patternkit-smoke-test` CronJob is the sanitized, intentionally
disruptive post-deploy hook. It verifies unauthenticated GitLab redirects,
synthetic authenticated Studio and Atelier catalog access, exact revision
parity, and the isolated workbench Kasm surface without loading or printing
private profiles or measurements. It opens an authenticated event stream, touches
`studio.py` without changing its contents, and requires that stream to close and
recover within seconds as behavioral proof of hot reload. Its namespace Role can
only get, watch, and patch the named Pattern Kit Deployment; it changes one pod
template annotation to exercise a Recreate rollout, then proves that the
sanitized PVC-backed collaboration session retains the same `created_at` value.
The smoke also runs the bridge's fail-closed lifecycle contract for restart, tab
switch, copied URL, stale target, duplicate nonce, and wrong-origin cases.

```sh
kubectl -n ai create job --from=cronjob/patternkit-smoke-test \
  patternkit-smoke-test-$(date +%s)
```
