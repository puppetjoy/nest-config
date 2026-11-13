# Joyride TEST component readiness isolation

This is a source-only candidate. It authorizes no merge, delivery, restart,
private-route replay or production change. Application admission/health scheduling,
cold-graph repairs and frontend work remain with the parent investigation.

## Workload contract

| Component | Deployment and exact `app` selector | Existing Service | Port |
| --- | --- | --- | --- |
| web | `joyride-test` | `joyride-test-web` | 8000 |
| internal-web | `joyride-test-internal-web` | `joyride-test-internal-web` | 8003 |
| ops | `joyride-test-ops` | `joyride-test-ops` | 8001 |
| trusted-test | `joyride-test-trusted-test` | `joyride-test-trusted-test` | 8002 |
| worker/bootstrap | `joyride-test-worker` | none | none |

Each Deployment contains only its named application container. Template labels
also provide `app.kubernetes.io/component` and `joyride.nest/application` identity.
Services use exact, disjoint `app` selectors, not a shared readiness condition.
No `publishNotReadyAddresses`, health-check removal or probe substitution is used.
Both web listeners retain HTTP startup/liveness and manifest-resolving `/sign-in`
readiness. Existing ops/trusted TCP probes are unchanged, not replacements for
HTTP checks. HTTP request and graceful/drain timeouts, worker counts and each
existing container's resources, security context and mounts are unchanged.

Keeping `joyride-test` as web preserves its immutable Deployment selector and the
backup helper's precise `app=joyride-test`, `-c web` contract. No overlapping
Deployment selector, immutable-selector patch or arbitrary-pod fallback is used.
The existing ingress names, hosts, paths and ports are unchanged: ordinary `/`
still targets internal-web, `/ops/` targets ops and the exact propose path keeps
its separate existing response timeout. Private proxy and authoring transport
configuration are unchanged.

NetworkPolicy retains its exact ingress peers and allowed ports. Its target
selector is an explicit `app In [...]` set covering these five workloads and the
original shared pod during transition. The original pod never escapes policy
because it lacks a newly introduced common label. Stripe still targets only the
public web app selector and its unchanged Service. No Service, RBAC or listener
is added for the worker.

## Measured routing health execution capacity

Component-specific readiness prevents one listener from withdrawing sibling
endpoints; it does not reserve execution capacity within a synchronous listener.
Parent integration measured liveness queuing for 1.997625 seconds behind a
synthetically held two-second detail request, exceeding the unchanged one-second
probe deadline. The isolated three-thread candidate responded in 0.001866 seconds
for liveness and 0.001281 seconds for actual database readiness; a competing detail
received HTTP 503 while the noncommitting profile helper returned HTTP 200.
These short synthetic-hold receipts establish execution-capacity isolation, not
historical storage latency, installed availability or arbitrary-load guarantees.

Only TEST internal-web and trusted-test add `--threads 3` to their existing two
Gunicorn workers. Gunicorn selects gthread for this setting. This must ship with
the parent application's one-expensive-dispatch-per-process admission, shared
between review and API dispatchers; threads alone do not bound expensive work.
Authentication and listener authorization precede admission; cheap health and
metadata stay outside it. Public web and ops serving commands are unchanged.
Existing resources, probe handlers, worker counts and timeout argument values
remain unchanged, as do all image/mail, mount, secret and network boundaries.

The guard is process-local, not a global queue. Threads cannot guarantee progress
against a native call holding the interpreter lock or arbitrary connection floods.
Gthread's worker heartbeat is not an operation-level request cancellation deadline;
unchanged `--timeout` values must not be represented as identical synchronous
request-kill behavior. Parent owns application exact-head CI, admission/thread
integration, live endpoint/health/geometry verification and eventual delivery.

## Saved-route graph memory capacity

The owner internal-web listener reserves 1 GiB and permits 2 GiB. The fixed
regional SQLite graph is 1,231,237,120 bytes, before Python/SQLite runtimes,
decoded route objects and page cache. Its former 768 MiB cap left both admitted
requests blocked in CephFS memory-mapped page faults; an in-place increase to
2 GiB released those requests without restarting the pod. This is a measured
capacity correction, not a claim that every storage wait is caused by memory.

The hard limit includes charged filesystem cache. A small process RSS alone is
not proof of headroom. Check `memory.current`, `memory.stat`, limit events and
actual request progress together. Preserve admission, integrity validation and
existing timeouts. The trusted TEST listener already permits 2 GiB; public web,
ops, worker/bootstrap, production and independently selected releases are outside
this change. Regress the actual rendered owner listener's request and limit so
component isolation cannot silently retain the old capacity.

## Single bootstrap owner and reader ordering

Only the worker/bootstrap Deployment retains, in order:

It alone owns the writable receipt path `/data/.bootstrap`; the receipt is outside
`/data/private`, the writable ops/trusted application subPath. All readers mount
whole `/data` read-only and only wait for this worker-published receipt. A fresh
recovery runs the bootstrap sequence again and publishes a new receipt; it does not
rely on restoring or copying a backup receipt.

1. migrate;
2. provision-owner;
3. basemap bootstrap;
4. checksum-bound private package fetch;
5. initialize-only private import;
6. immutable routing graph installation;
7. publish a small bootstrap-complete receipt.

Reader init containers only wait on that receipt through a read-only data mount.
They receive no private package input, artifact-verifier credential or pull-secret
volume mount. The existing Kubernetes image-pull reference remains. Their
application mounts keep the original read-only whole-data mount and, for ops and
trusted authoring only, the original writable private subpath.

Receipt identity binds the image's baked full `BACKEND_REVISION`, the checked
initializer recipe hash, the actual routing-installer SHA256 and the gate script's
own bytes. A different source, initializer recipe, installer or gate cannot reuse
an earlier receipt. The script-hash annotation triggers managed replacement after
a gate change. `test_component_readiness.py` checks recipe-hash maintenance; update
that declared hash when deliberately changing the initializer recipe. The receipt
has no mutable current pointer, graph scan, application endpoint or release
selection. It is published atomically only after all real initializers succeed.
Compatible surge initializers retain existing idempotence and database/lease locks.

A fresh reader waits in init without startup/liveness probes running. Failed or
missing bootstrap therefore cannot create a listener liveness loop. Normal HTTP
readiness still verifies the DB-backed selected frontend after initialization;
the receipt does not replace application readiness or continuously certify data
integrity. Existing bootstrap corruption remains a repair boundary. Retained
receipts and old graphs/releases are not deleted by this change.

## Managed delivery and rollback

The TEST controller receives GET/PATCH authority for exactly the five Deployment
names, never list/wildcard/pod authority. A new journal records every original UID,
image set, non-image footprint, prior delivery annotation and one original
1800-second deadline before claim. JSON Patch retains UID/resourceVersion tests
and changes only images plus the delivery annotation. It updates and observes the
worker first, then the four readers, and requires exact replacement generation,
replica readiness/availability and a final all-workload read after the existing
anonymous application probe. An old ready replica cannot satisfy completion.

Interrupted or uncertain writes resume the same journal and delivery identity;
already applied components are not blindly patched again. Any competing footprint,
selector, UID or shape change fails closed. A rollback operation uses the same
fleet path and selected immutable digest, with no automatic schema/data rollback.
The historical single-pod helper/tests remain for retained contract coverage but
the runtime entrypoint invokes only component delivery. A retained pre-split
journal is refused, not translated, overwritten or replayed.

## Direct consumer audit

- **Delivery controller:** adapted from one exact Deployment to this exact fleet;
  interruption, worker-before-reader and all-initializer image tests are included.
- **Backup:** the independently pinned helper with SHA256
  `0bd5c397f068b7e9eed784ce48afcd0abf4eeb4ae3b5a11c53aaa04939415f5c`
  selects one Ready `app=joyride-test` pod and executes `-c web`. This remains the
  unique web workload, with unchanged read-only data access. Database selection,
  full private/public/maps archive, stable-file checks and retention are unchanged.
  A rolling overlap is still refused as ambiguous rather than choosing a pod.
- **Monitor:** the pinned monitor uses `joyride-test-web.test.svc:8000`, not pod
  enumeration. Its health/session/map/home checks remain valid and unchanged.
- **Stripe/private proxy:** existing Service DNS, ports and header/route boundaries
  are unchanged. The real pinned-nginx fixture remains a separate acceptance lane.
- **Operator/delivery verification:** resolve the named Deployment's actual selector
  and component, not the former aggregate pod. Use `joyride-test-worker -c worker`,
  `joyride-test -c web`, and the matching named Deployment/container for each other
  listener. Check all five template image digests and replacement generations.
  A successful web-only image/readiness check is no longer fleet delivery proof.

## Integration and approval gates

Before any separately approved managed TEST transition:

- Refresh authoritative main and preserve its accepted immutable application image,
  SMTP account/from identity, environment-specific secret references and allowlist.
  This source phase does not publish the parent's application candidate or select
  another graph/frontend/content release.
- Require a settled original Deployment and idle deployment queue/journal. Do not
  change topology during an existing delivery or bootstrap. Keep the prior source
  and image for an explicitly reviewed rollback; do not reverse migrations.
- Review first-cutover availability explicitly. Helm changes the three private
  Service selectors while creating their new workloads; a single Helm apply is
  **not** a zero-gap initial cutover. It can temporarily leave those Services with
  no Ready endpoint. The existing public web Deployment retains RollingUpdate
  protection. Subsequent same-topology image updates use per-component
  `maxUnavailable: 0`, `maxSurge: 1` and `minReadySeconds: 10`. If a gap-free first
  private-listener transition is required, separately prepare a staged managed
  migration before approval; do not patch live selectors around this candidate.
- Capacity-check the actual five-pod topology. Existing application container
  requests/limits are identical, but scheduling init maxima across separate pods,
  pod overhead and four additional bounded scratch volumes are different from
  one shared pod. This is not resource tuning or a pre-approved capacity increase.
- Preserve graph bytes/current selection, DB review/revision hashes and independently
  selected frontend/content identities before and after managed delivery.
- Verify exact rendered Service selectors, actual EndpointSlices per component,
  fresh bootstrap ordering, managed promotion and rollback, private authoring
  isolation, concurrent meaningful health and the parent's selected geometry.
  Render-level selector/readiness assertions are not a live EndpointSlice test,
  private-route acceptance or a claim that cold graph/health starvation is fixed.

Production data/configuration and dormant activation gates are unchanged.
