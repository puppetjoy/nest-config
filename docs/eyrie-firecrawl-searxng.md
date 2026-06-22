# Eyrie Firecrawl + SearXNG validation stack

This private Eyrie web-research stack backs Hermes `web_search` and
`web_extract` without a Tavily dependency. SearXNG provides private
metasearch and Firecrawl provides page/PDF extraction plus a SearXNG-backed
search API for smoke testing.

## Components

- `searxng` in the `ai` namespace, deployed from the `searxng/searxng` Helm
  chart. It is exposed privately at `https://searxng.eyrie/`, enables HTML and
  JSON result formats for backend validation, leaves the public-instance limiter
  disabled because this is private Eyrie ingress rather than an Internet public
  instance, and keeps a small persistent cache/Valkey state on `owl-crypt`.
- `firecrawl` in the `ai` namespace, deployed from the packaged Firecrawl Helm
  chart at `oci://registry-1.docker.io/winkkgmbh/firecrawl` version `0.2.0`,
  with official `ghcr.io/firecrawl/...` workload images because the only Eyrie
  compute target for this stack is x86_64. It is exposed privately at
  `https://firecrawl.eyrie/` and wired to the in-cluster SearXNG service at
  `http://searxng:8080`.

The stack deliberately leaves hosted AI/parser credentials empty. Firecrawl's
self-hosted search/scrape path should work with fetch/Playwright and SearXNG;
AI extraction or hosted PDF parsing can be added later with private Hiera/eyaml
secrets if Joy wants those features.

`nuqPrefetchWorker` is disabled for this validation deployment: the upstream
chart starts it before the packaged database schema contains the
`nuq.queue_crawl_finished` relation, while the API, queue worker, extract worker,
Playwright, Redis, RabbitMQ, and NuQ worker are enough for the bounded
search/scrape validation path.

## Deploy/render entry points

Render only:

```sh
bolt plan run nest::eyrie::ai::deploy_searxng render_to=/tmp/searxng.yaml
bolt plan run nest::eyrie::ai::deploy_firecrawl render_to=/tmp/firecrawl.yaml
```

Deploy after review/approval:

```sh
bolt plan run nest::eyrie::ai::deploy_web_research init=true
```

Routine updates can omit `init=true` after the first successful deployment.

## Health checks

After deployment, verify Kubernetes and private ingress:

```sh
kubectl -n ai rollout status deploy/searxng
kubectl -n ai rollout status deploy/firecrawl-api
kubectl -n ai get deploy,svc,ingress,certificate searxng searxng-valkey firecrawl-api firecrawl
curl -ksf https://firecrawl.eyrie/v0/health/readiness
curl -ksf 'https://searxng.eyrie/search?q=Hermes+Agent&format=json'
```

Firecrawl's chart also creates API liveness/readiness probes on
`/v0/health/liveness` and `/v0/health/readiness`; the SearXNG chart creates TCP
startup/readiness/liveness probes and enables its built-in chart connection
test.

## Bounded functional smoke test

The `firecrawl` KubeCM data includes a suspended CronJob named
`firecrawl-smoke-test`. Run it manually after the stack is healthy:

```sh
job=firecrawl-smoke-test-$(date +%s)
kubectl -n ai create job --from=cronjob/firecrawl-smoke-test "$job"
kubectl -n ai wait --for=condition=complete --timeout=15m "job/$job"
kubectl -n ai logs "job/$job"
```

The smoke test calls the in-cluster Firecrawl API and checks:

1. readiness endpoint returns success;
2. `/v1/search` returns non-empty SearXNG-backed results;
3. `/v1/scrape` extracts markdown from `https://example.com/`;
4. `/v1/scrape` extracts markdown from a small W3C dummy PDF;
5. a negative localhost/unreachable scrape fails cleanly instead of producing a
   false success.

If the PDF case fails only because self-hosted Firecrawl needs a parser key for
some PDFs, keep the stack but record that as a cutover blocker; do not point
Hermes at Firecrawl until representative PDFs pass or the backend can fall back
safely.

## Initial validation evidence

From this worktree, the stack rendered with KubeCM/Helm and was deployed live to
the `ai` namespace for validation. Final smoke-test output:

```json
{"endpoint":"http://firecrawl-api:3002","health_seconds":0.045,"negative_seconds":0.028,"negative_status":400,"ok":true,"pdf_seconds":0.12,"scrape_seconds":0.206,"search_results":3,"search_seconds":3.903}
```

Private ingress was also checked by resolving both hostnames directly to the
compute ingress VIP before the DNS/Puppet follow-through has merged:

```sh
curl --noproxy '*' --resolve searxng.eyrie:443:172.21.3.0 -ksS \
  'https://searxng.eyrie/search?q=Hermes+Agent&format=json'
# -> 17 JSON results

curl --noproxy '*' --resolve firecrawl.eyrie:443:172.21.3.0 -ksS \
  'https://firecrawl.eyrie/v0/health/readiness'
# -> {"status":"ok"}
```

The source adds `firecrawl.eyrie` and `searxng.eyrie` CNAMEs; normal hostname
resolution still needs the source merge plus the usual Puppet/DNS follow-through.

## Hermes cutover

Hermes profile configuration is managed by `nest::lib::hermes`:

- `web.search_backend: searxng` with `SEARXNG_URL=https://searxng.eyrie` for
  native `web_search`;
- `web.extract_backend: firecrawl` with
  `FIRECRAWL_API_URL=https://firecrawl.eyrie` for native `web_extract`;
- shared `web.backend: firecrawl` as the fallback backend.

The public Firecrawl/SearXNG endpoints are private Eyrie ingress names and do
not require a Firecrawl API key. Roll back the cutover by reverting the Nest
config commit that changed `nest::lib::hermes` from Tavily to the local
Firecrawl/SearXNG backend, then reapplying Puppet to refresh the affected
Hermes profile config and environment.
