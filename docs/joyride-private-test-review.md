# Joyride private TEST kickstart review (historical evidence)

Canonical program: ^1981 / `t_befb85e8`.

The [original review](https://gitlab.joyfullee.me/nest/config/-/blob/874a0a9e16abeb2c61b96e0ff9e67509642309a0/docs/joyride-private-test-review.md)
preserves the TEST acceptance and settings at the time. TEST and production now
run separately; see the [current environment boundaries](joyride-environment-boundaries.md)
for live delivery and deliberate production promotion. Do not reuse old pins,
skipped CI, or approval records as instructions for new releases.

This review describes the reduced photos-only v1 and the separately authorized
sandbox billing phase. It is not approval to launch full membership in production.
The one-time public informational site is RETIRED under Joy's 2026-10-21
instruction; its earlier publication approval no longer applies.

## Where to review

- Private application TEST: https://joyride-test.eyrie
- Public informational site: RETIRED; not a review surface or future launch path.
- Application source: https://gitlab.joyfullee.me/joy/joyride
- Infrastructure source: https://gitlab.joyfullee.me/nest/config
- Frontend delivery: Luna, with Joy retaining editorial and business decisions.
- Platform/backend, source-managed operations and reliability: Talon.

At this review checkpoint routine mail was disabled. The review did not
exercise open public signup;
synthetic login fixtures used for engineering checks do not establish mail receipt,
member identity, payment, or human legal assent. Do not create memberships or legal
acceptance records just to make review convenient.

## Architecture and durable ownership

One cohesive Django/PostgreSQL application and small database-backed worker serve
Joyride. Puppet/Hiera/KubeCM manage TEST runtime, encrypted credentials, storage,
TLS, scheduled protection and the ordinary image baseline. Private curated input
is checksum-bound and installed transactionally/idempotently. Original media and
private route coordinates remain separate from coordinate-free public silhouettes
and the open regional basemap.

Luna has their own GitLab identity and project access, ordinary project CI and the
existing narrow TEST deployment/backchannel. They do not need a Talon ticket for
routine frontend updates. The project-specific ordinary Owl runner builds both image
architectures. The small importer/adapter checks exact source/CI/image/workload
identity and reports terminal TEST results. It is not a production approval system.
The discarded signing/custody/supervisor framework and unused dedicated credential
scopes are not acceptance prerequisites and must not be resurrected.

Deployment mechanics, rollback and cleanup inventory:
[`joyride-test-deployment.md`](joyride-test-deployment.md).
Environment/listener/credential boundaries:
[`joyride-environment-boundaries.md`](joyride-environment-boundaries.md).
Protection and restore scope:
[`joyride-test-recurring-protection.md`](joyride-test-recurring-protection.md).

## Previously verified milestones retained without redundant canaries

These are distinct historical executions, not new tests of every feature in this
review run. The detailed current ledger and chronology are maintained in
[`joyride-v1-acceptance.md`](joyride-v1-acceptance.md).

- Luna's independent Git/CI/backchannel forward and scoped rollback passed. Earlier
  failed preview attempts remain failed; subsequent successful operations do not
  erase them. TEST's replacement-resilient terminal status is not just HTTP 202.
- The supplied photos-only member frontend renders on desktop and phone: one
  available supplied route, real elevation, GPX, all 19 photo placements over 18
  originals, lightboxes and a painted self-hosted basemap. Source hashes and
  private intake are verified; other candidate routes remain unavailable.
- Exact current waiver plus active entitlement gates private route, GPX and member
  photo access. Missing/wrong waiver, canceled/unverified/anonymous identities,
  original/public photo URLs and retained video exposure are denied. Derivatives
  are EXIF-free. Synthetic fixtures were removed, not turned into business policy.
- Actual hosted Stripe sandbox success, decline, abandonment, return-alone denial,
  signed-event ingestion and authoritative reconciliation were exercised. The
  successful synthetic subscription was canceled. Actual portal navigation uses
  the supplied active-member UI. Locally signed duplicate replay verifies app
  deduplication, not a genuine provider retry.
- The sandbox uses the approved TEST Price and recoverable encrypted provider
  material. The official outbound Stripe CLI supplies private webhook transport;
  this is not registered public-endpoint or production delivery evidence.
- The shared managed SMTP path and sender identity have an approved bounded
  send/receipt milestone. Routine mail and member communications remain off.
- The regional OSM-derived basemap supply chain, range serving, attribution and
  private-route separation have prior evidence; no paid map provider or scraped
  public raster-tile dependency was introduced.
- Managed backup and exact-generation isolated recovery, plus separate populated
  photo/authorization restore, have distinct successful receipts. An empty managed
  database restore is not misrepresented as the populated-photo drill. Monitoring
  is source-managed; controller readiness alone is not application acceptance.

## Approved WMATA change in this review

Joy directly resolved the existing private TEST editorial/terms decision. Luna
identified approved source `eb2a32f79996474b11e51f8db1c406ff9b86bc42`, superseding
the old preserved draft. Application MR 20 integrates that exact fragment and its
approved line-chip styles into current main without a frontend redesign, portal
regression, media change or new publication policy. All 35 release file hashes
match at integration source `82f806d9296b98d8ec46d7eb82903679b67fd857`; the fragment
is byte-identical to the approved source. Luna also corrected stale release notes.

The concrete terms review at https://developer.wmata.com/license distinguishes
own-application display from the prohibited independent Transit Data API. Rendering
is server-side, escaped, authenticated and waiver/entitlement-gated; no raw feed,
JSON incident API, exported incident payload or browser credential is added. The
component identifies WMATA, supplies fetch/update timestamps and the terms link,
labels stale data, and omits disabled/unavailable states. Rendering reads the
private cache without an upstream request. Fixed upstream HTTPS, bounded bodies,
managed-key secrecy, minimum polling interval and sanitized failures remain.

Required pipeline 10964 check/build/PostgreSQL smoke passed. Optional CI preview
44241 failed before admission with `preview_observation_failed` / `not_requested`;
it is not a successful preview. Luna's existing scoped backchannel operation
`698d9f39-d2bc-4b0a-a75d-3e809797f3ce` succeeded on immutable image
`sha256:a4ad5a79bfaef70ad3edbd3ef5b466dbd05a3c25a1dc3ba057a6274dab0e3987`.
Application MR 20 merged as `14c28f8a4c76e6fe0084704ffef80ec22d224838`; the
merged tree is identical to the exercised source. Merge CI was deliberately
skipped so the unrelated public informational release did not run.

Run 12096 independently verifies the actual installed member panel on desktop and
phone, with colored line chips and sourced timestamps. There were no page errors,
external requests, browser transit API calls or horizontal overflow. Responses
are private/no-store without validators. The supplied route/photos remain present.
Installed rollback-only probes verify six render cases, escaping, stale warnings,
real cache-state classification and anonymous/unverified/canceled/expired plus
missing/wrong-waiver denial. Template and feed paths do not expose Transit Data.
Live cache refresh remains healthy. Fixtures and exact sessions were removed.
No incident text is copied into evidence or attachments.

The first browser harness attempt returned a generic Playwright error and cleaned
its fixture; it is not counted as passing. The rerun with Node explicitly using
the installed system CA bundle passed both viewports without any TLS bypass.
No local PDK/unit commands ran; required exact-source CI and actual installed
behavior provide verification. The review-era pins identified the tested artifact. At that point the matching
production pin was not a deployment receipt.

## Honest limitations and closed authority gates

- This is private TEST, not a full-membership production launch or production
  reliability signoff. The TEST review did not exercise production credentials,
  private administration, migrations, release or rollback. Today's production
  app deployment does not by itself authorize membership launch, payments, or
  content publication.
- No live Stripe payment, production webhook-delivery proof, routine email/member
  announcement or new public-content publication is included.
- No fixture establishes real legal assent. Waiver text/version stays verbatim;
  legal policy and membership/guest eligibility remain Joy's decisions.
- Photos only is the v1 scope. Real scout video and the historical motion-test clip
  are out of scope, not pending acceptance or shipped footage.
- Only supplied available route data is installed. Unavailable routes, invented
  coordinates/elevation and absent source material are not claimed as delivered.
- Prior failed builds, registry HTTP 503 and preview observations remain explicit
  in the ledger. CI badge color is not independent proof of a deployment result.
- Public feed redistribution is not authorized by either TEST display approval or
  the member authentication boundary. WMATA termination/data-removal duties remain.

Current-scope private TEST application acceptance is verified. This is not
production readiness, new public publication approval or permission to repeat
closed canaries. Historical evidence, failures and the remaining authority gates
stay explicit in the linked ledger and operational handoffs.
