# Honcho local embeddings migration

This branch stages Honcho's vectorization move from OpenAI `text-embedding-3-small`
to a private `honcho-embeddings` OpenAI-compatible endpoint in the `ai`
namespace.

## Model and serving choice

- Service: `honcho-embeddings` in namespace `ai`.
- Runtime: existing Nest llama.cpp tool image, `registry.gitlab.joyfullee.me/nest/tools/llama.cpp:zen5`.
- Model: `ggml-org/bge-m3-Q8_0-GGUF`, file `bge-m3-q8_0.gguf`, fetched by an init container into the service PVC and served from `/cache/models/bge-m3-q8_0.gguf` because the current llama.cpp image lacks HTTPS support for direct `--hf-repo` downloads.
- Endpoint: `http://honcho-embeddings/v1/embeddings`.
- Dense vector dimension: `1024`.
- Input window: `8192` tokens.
- Scope: private ClusterIP only; no ingress and no provider API key.

Rationale: BGE-M3 is a small multilingual retrieval model with 1024-dimensional
dense embeddings and 8192-token context.  The existing `llama-qwen` service is
not reused because the live probe returned HTTP 501 from `/v1/embeddings`:

```text
status 501 body {"error":{"code":501,"message":"This server does not support embeddings. Start it with `--embeddings`","type":"not_supported_error"}}
```

## Current live state before migration

Observed from the running `honcho-api` pod before this branch changed source:

```text
public.documents.embedding        vector(1536), non-null rows: 73517
public.message_embeddings.embedding vector(1536), non-null rows: 8947
HNSW indices: ix_documents_embedding_hnsw, ix_message_embeddings_embedding_hnsw
```

Honcho's startup validator refuses to boot if `EMBEDDING_VECTOR_DIMENSIONS`
does not match both pgvector columns.  Therefore the Honcho config change to
`EMBEDDING_VECTOR_DIMENSIONS=1024` must be deployed only as part of the
reviewed migration window below.

## Render and endpoint preflight

Render source before any live apply:

```bash
cd /home/joy/projects/nest/config
bolt plan run nest::eyrie::ai::deploy_honcho_embeddings render_to=tmp/render/honcho-embeddings.yaml
bolt plan run nest::eyrie::ai::deploy_honcho render_to=tmp/render/honcho-local-embeddings.yaml
```

After review, deploy only the embedding endpoint first and leave Honcho on the
old config until the endpoint is healthy:

```bash
bolt plan run nest::eyrie::ai::deploy_honcho_embeddings
kubectl -n ai rollout status deploy/honcho-embeddings --timeout=30m
kubectl -n ai run honcho-embedding-probe --rm -i --restart=Never \
  --image=docker.io/curlimages/curl:8.11.1 -- \
  sh -ceu 'curl -sS http://honcho-embeddings/v1/embeddings \
    -H "content-type: application/json" \
    -d "{\"model\":\"bge-m3\",\"input\":\"Joy asks Talon to keep memories local.\"}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); v=d[\"data\"][0][\"embedding\"]; print({\"count\": len(d[\"data\"]), \"dim\": len(v), \"first3\": v[:3]})"'
```

Expected probe shape: one embedding with `dim: 1024`.  Record latency with
`curl -w '%{time_total}'` during rollout.

## Backup gate

Treat the rest as a destructive data migration.  Take and verify a Honcho backup
before changing schema or clearing embeddings:

```bash
bolt plan run nest::eyrie::ai::honcho::backup namespace=ai service=honcho service_name=honcho
kubectl -n ai get cronjob/honcho-backup jobs -o wide
```

Do not proceed until the backup artifact/timestamp is verified and a restore
point is acceptable.  The known restore path is `nest::eyrie::ai::deploy_honcho
init=true`, followed by normal mode `init=false`.

## Migration window

1. Stop Honcho writers/workers:

   ```bash
   kubectl -n ai scale deploy/honcho-api deploy/honcho-deriver --replicas=0
   kubectl -n ai wait --for=delete pod -l app=honcho --timeout=5m || true
   ```

2. Run the checked-in schema/data migration script from a Honcho image pod with
   the new local embedding environment.  The script is stored at
   `files/kubernetes/honcho-local-embedding-migration.py` and performs the
   reviewed migration flow without printing message/document content.  It will:

   - Lock `documents` and `message_embeddings`.
   - Drop HNSW embedding indices.
   - Clear old OpenAI vectors.
   - Alter both columns to `vector(1024)`.
   - Recreate the HNSW indices with cosine ops.
   - Re-embed every non-deleted document from `documents.content`.
   - Re-embed every message from `messages.content` into fresh
     `message_embeddings` rows, preserving `message_id`, `workspace_name`,
     `session_name`, and `peer_name` metadata.
   - Mark `sync_state='synced'`, `last_sync_at=now()`, `sync_attempts=0` for
     pgvector mode.

   Use Honcho's `embedding_client` rather than handcrafted HTTP calls so token
   chunking, batching, and dimension validation match the application runtime.
   Documents store a single vector per row; if an existing document or message
   exceeds the local embedding model token or physical batch limit, the script
   retries that row individually with a truncated prefix and reports only an
   aggregate `truncated_overlong` count.  The truncation floor defaults to 512
   characters and keeps halving below that if llama.cpp still rejects a
   pathological high-token prefix, because the server's physical ubatch limit is
   lower than the configured embedding context.  If the script fails after
   completing documents but before completing messages/indexes, it may be
   resumed with
   `HONCHO_MIGRATION_SKIP_RESET=true` and
   `HONCHO_MIGRATION_SKIP_DOCUMENTS=true` after verifying document population.
   Keep batches modest (for example 128 documents/messages at a time) and print
   progress counts only, not message contents.

3. Deploy the Honcho config in this branch:

   ```bash
   bolt plan run nest::eyrie::ai::deploy_honcho init=false
   kubectl -n ai rollout status deploy/honcho-api --timeout=10m
   kubectl -n ai rollout status deploy/honcho-deriver --timeout=10m
   ```

## Post-migration verification

Run these checks before calling the migration complete:

```bash
# schema and population
kubectl -n ai exec deploy/honcho-api -- /app/.venv/bin/python /app/scripts/configure_embeddings.py --dry-run

# no OpenAI embedding credential in the pod spec
kubectl -n ai get deploy/honcho-api -o json | jq -r '.spec.template.spec.containers[].env[].name' | grep -E 'OPENAI|EMBEDDING'

# workload health
kubectl -n ai get deploy,pods,svc -l app=honcho -o wide
kubectl -n ai logs deploy/honcho-api --since=30m | grep -Ei 'embedding|openai|error|exception' || true
kubectl -n ai logs deploy/honcho-deriver --since=30m | grep -Ei 'embedding|openai|error|exception' || true
```

Expected config after this branch is deployed:

```text
EMBEDDING_MODEL_CONFIG__TRANSPORT=openai
EMBEDDING_MODEL_CONFIG__MODEL=bge-m3
EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL=http://honcho-embeddings/v1
EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY_ENV=HONCHO_LOCAL_OPENAI_API_KEY
EMBEDDING_MODEL_CONFIG__DIMENSIONS_MODE=never
EMBEDDING_VECTOR_DIMENSIONS=1024
```

Use Hermes/Honcho semantic recall as the functional test: query recent known
memories for Joy/Talon and Star, confirm relevant excerpts return, and confirm
queue counts drain or stay flat after normal traffic.

## Rollback posture

If the local endpoint or re-embedding fails before Honcho is restarted, restore
from the verified backup and redeploy the previous Honcho config.  If Honcho has
already started with the local config and recall quality is unacceptable, stop
Honcho, restore the backup, revert this branch's Honcho embedding env to OpenAI,
redeploy, and verify `vector(1536)` plus semantic recall before resuming traffic.

## Out-of-scope OpenAI consumers

This migration removes Honcho's embedding dependency on OpenAI.  It does not
remove OpenAI use by Hermes/Talon/Star for chat, image generation, TTS/STT, or
any non-Honcho service.
