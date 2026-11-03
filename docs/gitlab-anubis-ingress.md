# Public GitLab Anubis ingress

## Scope and topology

Only gateway's `gitlab.joyfullee.me` virtual host is filtered:

Internet → Apache TLS → loopback Anubis → TLS-verified `gitlab.eyrie`.

Anubis is the upstream filter proxy, not a new application or authentication
service. Its upstream Go reverse proxy supports HTTP upgrades. Using its direct
HTTPS upstream removes the extra unfiltered Apache routing listener from the
upstream Apache example. Both ordinary requests and WebSocket rewrite targets
point to the same filter. No alternate backend listener is introduced.

The image is upstream Anubis v1.28.2, pinned by its published OCI digest. No
Anubis package was present in gateway's configured repository snapshot; the
unconfigured GURU overlay is not added for one package. The existing
`nest::lib::container` and `nest::lib::secret` resources own the service and
signing key. The signing seed is Hiera-eyaml encrypted. The existing Podman
secret helper is create-once; key rotation requires an explicit controlled
secret replacement, not changing the encrypted value alone.

The filter and metrics listen only on IPv4 loopback. Metrics debug endpoints
are disabled, and the policy does not enable Open Graph passthrough or a
honeypot. The host CA bundle supplies the internal Eyrie trust anchor. TLS
verification is never disabled. The upstream Host remains `gitlab.eyrie`, as
with the previous proxy; the public forwarded host and protocol are explicit.

## Policy and identity

Every nonmatching request is explicitly challenged with fast proof of work,
difficulty 4. This includes empty or changed User-Agent strings and anonymous
REST/GraphQL. Firefox needs JavaScript and first-party cookies. Browsers with
JavaScript disabled and non-JavaScript crawlers lose direct web access; a
successful challenge is not proof of human identity or complete bot exclusion.
Signed, IP-bound, host-only clearance lasts 24 hours. Cookie names and GitLab
session-cookie presence never grant an exemption.

Narrow machine rules cover smart HTTP discovery/RPC, LFS protocol paths,
runner job/trace/artifact endpoints and the registry's scoped token endpoint.
They delegate actual authorization to GitLab. REST and GraphQL clients may
present a nonempty PAT or Bearer token; GitLab remains authoritative and must
reject invalid tokens rather than execute anonymous queries. Basic credentials,
empty Bearer credentials and user-agent names do not grant API exceptions.
There is no web-page exception for any Authorization/PAT header.

Apache disables automatic proxy header append and replaces X-Real-IP and
X-Forwarded-For from `CONN_REMOTE_ADDR`, not internet headers or a backend
address. It overwrites forwarded host/protocol and Anubis protocol/SNI metadata,
and strips client-supplied Forwarded and Anubis result headers. There is no
trusted-network allow rule. IPv4 and IPv6 clients use the same policy.

## Retired hostname

Remove the retired GitLab and registry aliases from gateway and Falcon proxy
source, local service discovery, SSH aliases and GitLab ActionCable origins.
Keep the current registry separate and unchanged. Gateway StrictHostCheck
rejects unconfigured hosts rather than serving the default virtual host.
Shared certificate material must remain; inspect each renewal lineage before
removing retired renewal/SAN configuration. Do not delete or revoke certificates
or alter unrelated james.tl services.

## Rollout and rollback

Validate source with PDK, run policy/Apache isolation checks, publish through
the request-bound MR, and require exact-head CI. Deploy the accepted main code
with `bolt plan run nest::puppet::deploy`, inspect a gateway Puppet noop, then
apply with `nest::puppet::run`. Prefer Apache's graceful reload. Do not restart
GitLab/Puma to mask saturation. The ActionCable origin change requires the
normal GitLab KubeCM deployment; keep its ordinary rolling update distinct
from an incident-masking restart.

The emergency proxy rollback is to restore gateway's previous destination
`gitlab.eyrie`, `proxy_ssl: true`, `preserve_host: false`, and remove the
Anubis-specific `extra_params` and class inclusion in source. Keep the retired
hostname removals. Validate, merge and converge through the same Bolt path.
Stop the filter only after the restored direct route is serving successfully.

## Evidence collected before rollout

A capped Rails sample covered 2026-11-03T19:19:33.642Z through
2026-11-03T19:20:19.739Z. It contained 864 anonymous requests with summed logged
request CPU of 78.253376 seconds and 49 authenticated requests with 5.104506
seconds. Webservice usage was 2079m CPU. These are request-log attribution and
an instantaneous Kubernetes CPU sample, not independently identified bots or a
whole-host CPU percentage. Preserve a fresh comparable sample at rollout.

The pinned image parsed the custom policy. The isolated request matrix passed
24 cases, including changed/empty User-Agent, fake session/clearance, fake
forwarded identity, invalid protocol shapes and WebSocket attempts. These
checks use a mock backend only to establish whether the real filter forwards;
they do not claim real GitLab authentication acceptance. Independent live
GitLab probes returned 401 for invalid PAT/Bearer credentials, while Basic and
empty Bearer could execute anonymously, explaining their exclusion.

An isolated Apache 2.4 configuration returned `Syntax OK`, forwarded a spoofed
identity request to the challenge, and rejected the retired Host with 400.
PDK source validation passed with the existing compatible syslog-closure image
after preserving/replacing the ignored stale generated lock. An attempted
additional unit integration test could not run because the intentionally small
fixture set omits puppetlabs-apache; the incomplete test was not retained.
Live activation, browser/protocol acceptance and effectiveness measurements
must be recorded separately; these preparation checks are not rollout success.
