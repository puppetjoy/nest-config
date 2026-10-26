# Joyride private TEST deployment

## Private routing engine

The enriched-history TEST selection follows Joyride MR 47, merged-main revision
`474f8f614b363f48199db94fc150f520a2399463`, pipeline 12278 with successful
check/build/smoke. Build 52537 `image.json` binds the multiarchitecture image
`sha256:437df0055eed4b7bb116b6ff1e9164342c9787362194b9ecbfb5ff2e1fd611b3`.
It retains cross-waypoint sidewalk continuity from MR 46. The immutable private
graph is `metro-20261026-v3`, 1,206,992,896 bytes, SHA-256
`9dcfaa2629a6a9d8a2903d5fd917b51b6fddbe55af49861a9d58ee098ad62886`.
This package enriches history without rebuilding topology: its `graph_build`
metadata remains `metro-20261025-v2`, preserving existing route bindings. Package
selection and expected topology identity are checked independently.
The existing installer verifies it before atomic selection, retaining v2 below
as `previous.sqlite3` and leaving older rollback bytes intact. No open inode is
overwritten. Contributing skates increase from 406 to 832, weighted edges from
10,114 to 12,578 and activity-edge uses from 36,516 to 68,190. These are conservative
local history contributions, not new whole-route matches or facility certainty.
Preserve active frontend, basemap and content; no release is published.

Historical v2 baseline and retained installer safety contract:

The TEST baseline now follows Joyride MR 42, merged-main head
`dd05b3ce7705fa1cfaee818b545d39b43f83694e`, successful pipeline 12204.
Build 52004 `image.json` binds the multiarchitecture image
`sha256:16f20746d48e8e9c7c48845951fd7ffc6e5dbec74bbfd68a978660f965eafd62`.
The previous managed image is the basemap v3 pin below. Preserve active basemap,
frontend and content selections; this installation does not publish a release.

The serial `routing-graph` initializer reuses the existing read-only package
credential and private project 83 generic package lane, without new RBAC. It
streams the checksum-named `joyride-routing-private/metro-20261025-v2` file to
the private PVC, verifies exact size, SHA-256, SQLite integrity, build metadata
and unresolved migrations before atomically selecting
`/data/private/routing/current.sqlite3`. Its immutable file is read-only and
retained. The source graph is 1,205,555,200 bytes with SHA-256
`f13481cb4e1ba95e28165d9259b692216acd635d2266ccc5cc1be6b6c89ca104`.
The installer checks staging capacity plus 256 MiB headroom; it neither expands
the existing 8 GiB PVC nor deletes retained data. A rerun verifies/reuses the
installed file without downloading it again. A changed selection retains the
old target under `previous.sqlite3`; no open graph is overwritten in place.
For rollback, select a retained verified graph atomically and retain both files;
change the managed installer selection as well so the next rollout agrees.
Download writeback is bounded to 16 MiB intervals. Full SQLite integrity checks
use a 1280 MiB read-only mmap budget and 8 MiB SQLite heap cache within this
serial initializer's 1536 MiB limit. Mapping shares the hash-warmed file cache
instead of duplicating the graph in heap memory and forcing random CephFS
rereads; steady-state app budgets are unchanged.

Only the private proxy forwards the five exact `/routing/*` operations to port
8002. JSON bodies are capped at 1 MiB, caller identity/auth headers are discarded,
and upstream timeouts match the trusted listener's existing 120-second budget.
Public, internal-web and bearer-ops listeners do not register routing URLs.
Production remains fail-closed and unapplied. See `joyride-luna-private-access.md`
and the application's `docs/internal-routing-engine.md` for the API contract.
Oregon carriageway/sidewalk remains unknown; installing this graph does not
resolve facility uncertainty or confer final route acceptance.

## Basemap v3 managed installation

The current TEST baseline follows application MR 40, merged-main revision
`6e7ebd228020f56e78fd1c7a9343300967eb9e0f`. Pipeline 11957 passed check,
build and smoke; build job 50154 supplies the authoritative `image.json`:
`sha256:bf6bf1128338399fdcb1d7483916d738a9e356b909d660f3599767a157883f6a`.
It retains the trusted TEST member correction below. All application listeners,
workers and initializers use this pin; the fixed controller interpreter and
Stripe listener retain their independent pins. Production is unchanged.

Installation registers immutable v3 without promotion. Require archive SHA256
`7c65d1bffdca7f429369b9f97b33ae893be7b4ba7bc0b1f9857acbb5c354c91b`
and manifest SHA256
`9a5a4a456a2929378246c5428980c966cecbac5413379dacf9a9c33e40ad5d28`.
Reuse the existing checksum-bound original sources. Retain v2, the older
`dc-md-va-20261018` release, and refreshed frontend/content ActiveRelease pointers.
V2 must remain active after this installation; promotion and external native-map
acceptance belong to the original basemap request.

Full v3 admission measured 617.410 seconds with one CPU and the existing 768 MiB
initializer limit (cgroup peak 567,357,440 bytes). TEST Deployment progress and
new delivery-operation deadlines are 1800 seconds, including download, admission,
startup and readiness. The TEST controller Job allows 1860 seconds for terminal
callback overhead; existing journaled deadlines are not extended or replayed.
The documented Bolt wrapper sets `wait: true`; current KubeCM emits Helm
`--wait --timeout 1h`, not a conflicting 600-second wait. That existing shared
upper bound is unchanged: the workload's progress deadline and controller's
installation observation remain bounded to 1800 seconds. Transport requests
remain short (15 seconds in the controller). No CPU, memory, PVC, replica or surge
budget is widened. Old-pod readiness cannot satisfy replacement completion.

From the isolated Nest project root, install the declared modules with
`bolt module install --no-resolve` if needed. The wrapper mounts that root as
`/modules/nest`, uses its `inventory.yaml` and `.modules` modulepath, and forwards
the current `KUBECONFIG`. Verify the intended Eyrie context, installed application
images, idle deployment queue/journal, immutable map hashes and release pointers
immediately before running `bolt plan run nest::eyrie::deploy_joyride_test`.
Read back exact replacement images, completed generation/readiness, file hashes,
v3 inactive/v2 active registry state and unchanged refreshed release pointers.

### Retained trusted TEST member correction

Application MR 41 is merged at `c37b2a3e32c9f00829fef9146483b0f411b16721`.
Main pipeline 11893, build job 49671, supplies the authoritative `image.json`:
`sha256:b6c833d4f0356b5763488078677d1b76e0b00d8b27774127bbec46ab48445924`.
This baseline retains later accepted main work. It does not interrupt the
independent v3 producer/archive, promote v3, replace v2 or publish frontend/content.
Every application listener, worker and initializer uses this single pin.
Require main check/build/smoke success and refresh installed identity before
deploying, so a newer accepted deployment is never overwritten silently.

The private member proxy now uses exact no-bearer routes on trusted port 8002,
not the former generic bearer prefix on 8001. Authorization and caller identity
claims are stripped, and private-access port 8001 network permissions are removed.
Legacy ordinary ops credentials/listeners remain unchanged. See
`joyride-luna-private-access.md` for methods, encoded email, audit cursors and
the mandatory installed pre-SNAT Tailscale/network-policy trust boundary.
The stored-token Muse connector/scope list is retired/disconnected. Parent-owned
Luna read/reset/readback/audit acceptance remains distinct from engineering
synthetic HTTP and installed-route verification; do not claim it from fixtures.

## Basemap v2 runtime baseline

The TEST pin follows application MR 37, source
`589e98cabde3b688f7ce523d78d5c1955018ae38`, merged-main revision
`69aa277afeec89535aa0c20d5bbcb7291f2bcd09`, pipeline 11710 (build 48238).
The immutable multiarchitecture image is
`sha256:c0da446de17b5fa19f5cf7e8297844040bc2ca992f98629ee0843733e3d65e1d`.
This retains the audited member administration from MR 36. There are no new
database migrations relative to that baseline. Production pins remain unchanged.

The basemap initializer requests 250 millicores and 192 MiB, with a 768 MiB
memory limit and no CPU limit. It streams the fixed archive and retained original
sources directly to the existing PVC, verifies hashes before atomic rename,
then performs full native z16 admission before registration. It does not rebuild
tiles or stage these downloads in the shared 1 GiB temporary volume.
The historical v2 full admission measured about
9.3 seconds independently, excluding downloads; v3 uses the bounded budget above.
Admission failure must retain
the prior serving pod, not weaken validation or delete existing map data.

Installing v2 does not promote it over an active map. Preserve the registered
`dc-md-va-20261018` archive and active flag, all release history, and the latest
frontend/content ActiveRelease pointers. Explicit map promotion and external
content/cache/range acceptance belong to the original basemap request, not this
managed runtime install. Both web mounts remain read-only. The previous runtime
image is `sha256:e12ad8eb2da7eaabcac6add447c3cabe63426617e17900c7dafc5b0fb2fc249c`.

## Compatible image rollout availability

TEST uses one steady-state pod plus at most one surge pod: `RollingUpdate`,
`maxUnavailable: 0`, `maxSurge: 1`, and `minReadySeconds: 10`. Both the managed
KubeCM baseline and the named-workload adapter preserve this contract. The
adapter refuses Recreate, percentage/default budgets and widened surge before
claiming work; it still patches only images and its delivery annotation using
UID/resource-version tests. An old ready pod cannot satisfy terminal success
while the replacement remains unready. A failed replacement stays failed; no
automatic schema/image rollback or deletion of the prior serving pod is added.

The two web readiness probes fetch `/sign-in`, which resolves the active frontend
through PostgreSQL and checks the manifest-bound bytes. This is stronger than
the DB-only `/health/ready`; it neither signs in nor sends email. Initializers
finish before any app listener starts. Startup probes allow two minutes for
listeners to start without premature liveness restarts. The replacement must
remain ready for ten seconds before the old pod is voluntarily removed.

All four Gunicorn listeners have a 15-second preStop endpoint-withdrawal window,
a 125-second graceful worker timeout and a 150-second pod grace budget. The ops
upload request timeout remains 120 seconds. This bounds draining, not an unlimited
connection-lifetime promise. Requests longer than the configured budgets, client
disconnects, node loss and external proxy failures remain outside that guarantee.

Overlap safety was checked against the installed favicon backend, not the older
bootstrap checkout. PostgreSQL sessions and the same managed Django secret are
shared; there is no pod-local session affinity requirement. Frontend activation
uses a shared CephFS publication lock, immutable checksum trees and a transactional
ActiveRelease pointer. Each reader resolves that pointer and serves verified
bytes. Curated content has its own shared import lock and installs its immutable
tree before committing catalog changes. Startup `--initialize-only` retains the
active curated revision; owner provisioning uses unique-email `get_or_create`
without altering verification, billing or waiver records. Basemap bootstrap uses
the already installed immutable files and does not reset an active promotion.
Missing/corrupt shared bootstrap data is a repair boundary, not permission to
delete data or race a fresh bootstrap across versions.

Workers claim rows with transactional `select_for_update(skip_locked=True)` and
lease fencing; maintenance/transit schedules use database locks and dedupe keys.
Overlap does not add a second independent schedule. This remains an at-least-once
worker: termination after an external side effect can leave work to its existing
ten-minute lease recovery. RollingUpdate is not an exactly-once email/payment
guarantee. No mail, payment, member or waiver canary is required for this rollout.

Only backward-compatible schema changes may use this ordinary path. Review all
new migrations for compatibility with the still-serving old code, lock duration
and rollback constraints before admitting the image. The existing migrate init
is retained; Kubernetes does not make destructive migrations safe. Use an
explicit expand/contract sequence or a separately planned, owner-approved
maintenance procedure for incompatible changes. Never conceal such maintenance
inside every routine release or automatically reverse a schema on timeout.

One surge adds 450 millicores and 896 MiB of requested memory (up to 5376 MiB of
container memory limits), plus its 1 GiB scratch-volume bound. The observed Kite
capacity admitted this small budget; insufficient scheduling capacity must leave
the old healthy pod serving, not relax maxUnavailable. Terminating pods can briefly
coexist with the serving/surge budget while they drain. This removes planned image
replacement gaps, not single-node, single-database, storage or ingress failures.
Production remains dormant and guarded; this is not a production HA claim.

## Owner dashboard and fast releases

The TEST baseline is application MR 32, merged-main pipeline 11600, source
`12fe36bc9ed33ddcae2d1717e41b4475c891f239`, image
`sha256:5537ffba7c6df3884bb7f7cb56c90fa925aa21d65c4436d741381b577d1fbf3c`.
Build job 47743 published this immutable multiarchitecture index. Catalog
fragments are selected server-side: anonymous responses omit development rows,
identifiers and titles from HTML and linked public assets, while qualifying
members retain their existing entitlement boundary. Catalog responses use
`Cache-Control: no-store, private` and `Vary: Cookie`. The actual-Route-only
template selection from MR 30 remains, without expanding proxy access.
Preview job 47745 already reached terminal success for deployment
`982f775b-58a1-4590-8ade-ee642d9e4d4c`; do not replay it for baseline
reconciliation. Anonymous ordinary HTTPS checks cover disclosure and cache
boundaries. Installed member-selection checks use synthetic identity/entitlement
inputs; they are not live authenticated HTTP acceptance.
It retains bounded bundle-defined galleries, mutable curated slugs,
OTP-first sign-in, 90-day sessions with hourly authenticated rolling renewal,
and branded mail from `Friday Night Joyride <joy@joyridedc.com>`.
The seasonal owner dashboard and manifest-bound favicon remain included.
Frontend/content releases remain independent of this backend pin; retain Luna's
active release and all release history. The verified active frontend is
`luna-frontend-v13-2026-10-23-r41`, archive
`6bcf767da398519bd413fbd86e57ab1d4aedc864ba79a8b3bd006dbbf1e7d626`;
content is `luna-content-2026-10-23-r8-rename-western-reach`, archive
`d7a765f44a9e5173bf7d2ff6f844aa9f1a9180c241762d698eca3f65c370ae2e`.
Both have source head `a0fe1b1ae59f7f02ed9e9270954d976b23c8fdba`.
The membership/dashboard URLs use one route brief at `/routes/western-reach`;
retired `/pages/*`, `/member/*` and old slug pages return real 404 responses.
The established checkout return remains `/checkout/return`, not `/checkout-return`.
Waiver `participant-v2-text-2026-10-23` has SHA-256
`17995e20a6a05eae5934b0cc2e905892f97bba3d43c8edfa43bc20c621202f3d`;
historical acceptances are retained unchanged and fresh acceptance is required.
A baseline apply must also retain the previous frontend r39 and content r7 archives.
A managed baseline apply must preserve both, not publish another release.
The previous managed image is
`sha256:0ffcc26acde46f6a969485564d3ce70ca7013a284d4c52e084720363096cc1a7`;
read the actual installed image again before any rollback.
Internal `.eyrie` ingress and the existing private backchannel use the separate
`joyride.internal_wsgi:application` listener on port 8003. Public WSGI remains on
8000 without owner routes. Owner access requires normal verified email sign-in;
the serial `provision-owner` initializer follows migrations and creates no session.
`OWNER_EMAIL` is server-managed, not a browser-supplied identity.

For frontend/private-content-only changes, use the existing private TEST channel:
`GET /ops/releases`, `POST /ops/releases/frontend` and `POST /ops/releases/content`.
These replace image CI as the routine frontend/content iteration path; image CI
and the delivery adapter below remain for backend/dependency/legal changes.
Upload the raw gzip archive with `Content-Type: application/octet-stream`,
`X-Release-Sha256`, `X-Previous-Sha256`, `X-Release-Version` and `X-Source-Head`.
The proxy accepts only those exact methods/targets: content admits 64 MiB compressed,
while frontend remains 32 MiB. Upload/upstream and ops Gunicorn budgets stay at
120 seconds. The content importer admits at most 128 MiB of files, 16 MiB per
JPEG, 2 MiB per metadata file, 64 originals, 128 placements and 160 tar entries.
Pixel bounds are 50 MP per image, 256 MP distinct and 512 MP placement-weighted.
Frontend unpacked bounds remain unchanged. Both paths validate compare-and-swap
and exact archive contents. See application `docs/content-bundle-v2.md` for schema.
HTTP 200 with `state=succeeded` is committed activation, not an enqueued operation.
Existing bearer ops callers require `release` scope; delivery credentials do not
gain release authority. No Kubernetes credential or new publisher is introduced.

Both web listeners retain read-only data. Only the scoped ops processes get a
writable `/data/private` subpath for curated trees and `/data/private/releases`.
The existing backup scanner/archive recursively captures all of `/data/private`,
including retained release archives; its pinned implementation remains unchanged.
Both curated import dry-run and apply use `--initialize-only`, retaining an active
revision across image restarts. Rollback uses the same endpoint with a retained
archive and current SHA. Never delete editorial data/history to force startup.

Ops, trusted-test and curated-import each have a 1536 MiB memory limit; requests
remain unchanged. Sequential JPEG decoding and disk-spooled checked archives
bound processing: the compressed snapshot plus tar needs roughly 193 MiB scratch
at the cap, within the existing 1 GiB shared tmp. The 16 MiB input volume still
fetches only the immutable r1 seed, not a newer gallery. The private PVC remains
8 GiB. On the pre-deploy Kite survey, 1414 MiB was requested and 6066 MiB limited
out of about 16086 MiB allocatable; one new surge adds 896 MiB requested and
5376 MiB limited. Capacity is not permission to widen maxUnavailable.

Bootstrap uses stable curated identity independent of mutable slug; both dry-run
and apply retain `--initialize-only`. A managed backend rollout does not publish
Luna's gallery or rename editorial routes. After v2 publication, rolling back to
a pre-v2 backend first requires using the new backend to restore a compatible
legacy content archive and slug. Never perform destructive automatic rollback.

Production remains guarded and dormant. Allowlisted SMTP and sandbox billing
remain unchanged. Deployment readiness, anonymous admin denial and baseline release
status do not replace Joy mailbox/sign-in or Luna release/rollback acceptance.

## Allowlisted sign-in email

TEST enables SMTP sign-in email using the existing encrypted runtime credentials.
`TEST_MAIL_ALLOWLIST` is exactly `joy@joyfullee.me,joyfulskater@gmail.com`.
This supersedes historical routine-mail-off notes below for TEST only;
production mail and membership remain dormant. Use the normal private
`https://joyride-test.eyrie/sign-in` flow. A request accepted by the application
is distinct from successful SMTP submission, and neither proves mailbox receipt.
Never consume a recipient's sign-in link or seed an owner session to verify mail.

Joyride uses the ordinary Eyrie application boundary: personal application CI
builds an image, and Nest pins an immutable image and supplies managed runtime
credentials, storage, PostgreSQL, TLS, private access, backups and monitoring.
Luna's self-service TEST updates retain the existing small artifact importer and
deployment adapter. These are the concrete consumer of the read-only GitLab
credential and exact-workload Kubernetes role, not the withdrawn signing,
custody, supervisor or production-attestation framework. There is no new service
or connector authentication ceremony.

For a routine frontend release, Luna pushes to `joy/joyride`, inspects its normal
check/build/PostgreSQL smoke result, and uses its existing manual `preview` job
or the private Tailscale `POST /ops/deploy` endpoint. The importer checks the
successful exact-head CI and immutable multiarchitecture digest. The adapter
changes only `test/joyride-test` images, verifies readiness and reports terminal
success/failure through status. HTTP 202 alone is not deployment success.

Luna receives no host, Bolt, Kubernetes or production authority. Her authorized
Tailscale path is authentication for its scoped listener; no connector token,
synthetic identity header or extra Tailscale-side service is needed. Ordinary CI
uses its existing scoped TEST credential, not host or infrastructure secrets.

For infrastructure deployment or a durable baseline pin, inspect ordinary app
CI and image identity, update `joyride_image` in this repository through review,
then run:

    bolt plan run nest::eyrie::deploy_joyride_test

Verify the actual deployed image, completed rollout, application readiness,
sessions, private-data authorization, basemap range responses and supplied
frontend. A ready Deployment alone is not application acceptance. Keep the
previous image digest available for an explicit reviewed rollback; assess
schema compatibility before rolling application code back.

The adapter's exact initializer allowlist includes `migrate`, `basemap`,
`curated-fetch` and `curated-import`, all from the same selected application
digest. Unknown or duplicate initializers remain refused before claim. Adding
private intake without updating that allowlist caused Luna's queued r5 operation
to fail before claim with `unexpected_workload_shape`; readiness and passing CI
did not prove delivery. Preserve that queued identity and all failed receipts
while installing the correction, then verify its actual terminal outcome. Do not
delete the operation, weaken workload-shape validation or deploy around it.

The supplied frontend, database/PVC, private listener, backup and monitoring
contracts remain unchanged. Only the adapter receives exact named-workload patch
authority; this change adds no Kubernetes credential to app containers or CI.
The adapter's nonsecret journal preserves interrupted-operation identity. Its
separate delivery credential cannot perform member or production operations.

Application MR 13 removes signed production receipt consumers and the unused
evidence publisher. MR 14 moves ordinary application CI to project runner 127.
Its merged-main pipeline 10866 passed check/build/smoke and published the reviewed
multiarchitecture image pinned here, installed on TEST generation 24 by preview.
The dormant production candidate pin stays aligned but its compile guard and zero
replicas remain unchanged; this does not activate production. Production delivery
is unconditionally denied, including with legacy enable variables. Historical
database records remain for non-destructive upgrades, not new admission.

The importer also discovers running pipelines, but admits one only when required
check/build/smoke and every other job succeeded and the sole pending work is the
optional preview. This prevents registration waiting on that preview's completion.
All exact project/source/pipeline/digest and architecture checks remain. Preview
waits boundedly for registration and then the terminal controller result; inspect
its retained `test-deployment.json`, not just the pipeline badge or HTTP 202.
See the personal application's `docs/delivery-status-contract.md`.

Luna already independently deployed a benign revision through pipeline 10829,
preview retry 43584. Its first preview hit the registration race. The operator's
later rollback was not Luna rollback acceptance. The changed waiting/terminal
contract and Luna's rollback still need live verification after this deployment.
Pipeline 10866 first preview 43738 failed observation during the replacement
rollout. Retry 43759 used the same idempotency key and deployment identity and
returned terminal success. Preserve both historical receipts. Application MR 15
adds bounded transport and gateway retries without changing identity or deadlines;
authorization, malformed responses and terminal failures remain fail-closed.
Merged-main pipeline 10892 passed every job on runner 127, including preview
43885, and independently reached terminal TEST success on the baseline pinned
here. Billing remains disabled and routine mail off. Checkout binding and
authoritative reconciliation hardening passed application tests; actual sandbox
payment, waiver and member-access acceptance are still original-owner work.
Use the verified actual pre-preview artifact for rollback, not the older delivery
row's previous_digest: managed deployments and that history can differ.

Current cleanup inventory (readback before this rollout):

- Removed from Nest source: signing/custody/supervisor collection and admission
  framework. Owl reports its supervisor inactive with no loaded supervisor unit;
  the checked evidence state/configuration directories are absent.
- Removed from application source and installed TEST: signing consumer/tools/
  publisher and custom production admission in MR 13. Preserve historical audit rows.
- Kept: DB/media, TLS, encrypted runtime/provider/pull/read-only verifier secrets,
  private Tailscale listener, ordinary health/backup/restore and the small TEST
  importer/adapter needed by Luna's self-service. The public informational site
  is RETIRED under the independent 2026-10-21 retirement request.
- Kept: project runner 127, now an ordinary instance of Owl's shared manager,
  for Luna's check/build/publish/preview. It has host-root Podman engine authority,
  but no directly injected eyaml/Bolt/Puppetcore credentials. See
  `joyride-ci.md` for the trust model and cutover procedure.
  All pipeline 10866 jobs ran on it, including terminal preview. Project 83 now
  disables shared and group runners; independent readback lists only runner 127.
  Shared Nest runners are unchanged. Dedicated unused credential scope revocation
  completed in private MR 13 after source/live consumer checks: only the two
  dedicated evidence registry readers were revoked. Necessary application,
  provider, pull, verifier, delivery and runner credentials remain.

Before managed activation, inspect pending/running deployment counts and existing
journal state. Do not replay old operations. After deployment, verify exact RBAC,
healthy schedules, app readiness, denied direct/public operations, private access,
storage, backups and monitoring. Preserve historical outcomes and app data.
Production promotion/rollback remains an explicit reviewed same-artifact operator
operation with Joy's publication/activation gates, not another signing service.

This is TEST only. Joy has authorized sandbox billing using the exact TEST price
price_1USr7ARxm5b9CJTLAsfCS7RO. Runtime billing remains disabled until encrypted
provisioning, the exact webhook transport and application/frontend integration
are verified; this pin reconciliation does not enable it. Routine mail stays off.
Private MR 13 supplies the recoverable encrypted sandbox key pair. The TEST
runtime Secret now projects the existing STRIPE_SECRET_KEY and
STRIPE_PUBLISHABLE_KEY contract, rejecting non-sandbox prefixes. The official CLI listener signing secret is now encrypted in private MR 14,
with independent merged-source recovery verified. Never invent a signing secret or
register the unreachable private .eyrie URL. Stripe documents its outbound CLI
listener as an option for private testing without a public gateway; that is not
proof of registered public-endpoint delivery or production readiness.
Production member platform activation, payments, member communications and content
publication retain their separate owner gates. The existing approved public
informational site and www redirect are retired and must not be regenerated.

The TEST-only outbound listener uses the official Stripe CLI 1.54.1 pinned to
its independently inspected multiarchitecture index. It refuses live key prefixes
and compares the provider's actual device-specific signing secret with managed
configuration before forwarding. It has no Service, ingress, Kubernetes token or
RBAC. Only the sandbox API key enters the forwarding process; raw CLI output is
suppressed because startup prints the signing secret. Billing remains disabled
until transport verification; process readiness is not provider acceptance.
Forwarding targets the internal web Service with the exact allowed Host header,
not an unreachable public registration. This does not prove production delivery.

The corrected official listener is installed in TEST at Helm revision 28. Its
actual process has passed the managed signing-secret parity gate, and its narrow
network path reaches the web Service with the required Host header. The exact
application workload was restarted to consume the encrypted signing secret;
independent running-settings readback confirms its presence without exposing it.
The TEST override now enables sandbox billing with the already approved TEST
price. Production remains disabled and routine mail remains off. Genuine signed
provider delivery, payment outcomes and waiver/member unlock still require live
acceptance after this setting is deployed; listener readiness is not that proof.

Luna's updated independent canary and rollback have now passed. Her comment-only
source b530be153c8292701365676133e80a9097ab6765 passed pipeline 10895, including
terminal preview 43899, entirely on runner 127. Independently read application
state confirms forward deployment 941104ca-f6ee-440d-b136-010e26688cb3 succeeded
on sha256:65bc1b91949e727edf0f9d66a649405cb3aa52c3810c79f85e55da87a5bedfa4,
then her scoped rollback 579c6106-332a-4812-80b2-08e0dd930ca3 succeeded on the
reviewed c5786b2b baseline. Actual Kubernetes images again match that baseline.
Historical preview failures remain failures, not overwritten successes. No
production, billing or routine-mail authority was added by this canary.

## Supplied private route and photos

Application MR 18 adds TEST-only `import_curated_private`. The TEST pod fetches
only the supplied project 83 generic package `joyride-curated-private`, version
`2026-10-18-r1`, with exact size and SHA256 verification before writing its private
ephemeral input volume. Redirects are refused so the existing read-only GitLab
credential cannot follow another host. Only the fetch init mounts that credential;
web, ops and worker containers never mount the package input or reader secret.

After migration and basemap initialization, the intake init first validates with
`--dry-run`, then applies through the transactional/idempotent application command.
One supplied route (`ride-001-cathedral-climb`) and 19 member photo placements over
18 originals are installed under the existing private PVC. Other candidate tracks
stay unavailable. Original GPX and actual scout/profile are distinct supplied
inputs; no invented elevation or video. Member derivatives strip EXIF and remain
private. No public source content is published by this operation.

Startup fails closed on fetch, archive, source or existing editorial/file drift.
Do not delete a conflicting private tree or DB rows to force startup: inspect the
application's `docs/private-curated-intake.md`, retain the prior image and reconcile
the exact conflict. A rollback retains all private data and database history.
The dormant production candidate pin stays aligned, but has no intake init and
remains guarded, zero-replica and unapplied. This is not production authorization.
