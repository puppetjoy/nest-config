# Honcho local embeddings migration (historical)

The [original migration record](https://gitlab.joyfullee.me/nest/config/-/blob/c14438ab942507b7312af6c65e3087f56c816dde/docs/honcho-local-embeddings-migration.md)
preserves the former schema, migration procedure, validation and rollback
posture. Those steps are not a current deployment or recovery runbook. Do not
replay the schema changes, re-embedding, or old rollback on live Honcho.

The normal Honcho deployment in `ai` uses the private `honcho-embeddings`
ClusterIP service, BGE-M3, and 1024-dimensional vectors. The maintained
[Honcho application data](../data/kubernetes/app/honcho.yaml) and
[embedding service data](../data/kubernetes/app/honcho-embeddings.yaml) describe
current intent. This changes neither the embedding configuration nor other
OpenAI consumers.

Use the existing [Honcho deploy](../plans/eyrie/ai/deploy_honcho.yaml),
[embedding service deploy](../plans/eyrie/ai/deploy_honcho_embeddings.yaml), and
[backup](../plans/eyrie/ai/honcho/backup.pp) paths as appropriate. The
[restore plan](../plans/eyrie/ai/honcho/restore.pp) remains an explicitly scoped
recovery operation, not part of a routine release. Readiness and a synthetic
embedding check do not establish database recovery or semantic recall.
