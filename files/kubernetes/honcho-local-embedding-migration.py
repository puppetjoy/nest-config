#!/usr/bin/env python3
"""One-shot Honcho pgvector re-embedding migration for local BGE-M3.

Run inside the Honcho application image with Honcho writers stopped and the
local embedding environment configured. The script intentionally prints only
aggregate counts/progress, not message/document content.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

# The Honcho image keeps the application under /app.
APP_ROOT = Path(os.environ.get("HONCHO_APP_ROOT", "/app"))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from sqlalchemy import delete, func, select, text, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src import models  # noqa: E402
from src.db import engine  # noqa: E402
from src.dependencies import tracked_db  # noqa: E402
from src.embedding_client import embedding_client  # noqa: E402

TARGET_DIM = int(os.environ.get("EMBEDDING_VECTOR_DIMENSIONS", "1024"))
DOC_BATCH_SIZE = int(os.environ.get("HONCHO_MIGRATION_DOC_BATCH_SIZE", "64"))
MESSAGE_BATCH_SIZE = int(os.environ.get("HONCHO_MIGRATION_MESSAGE_BATCH_SIZE", "64"))
DOC_MAX_CHARS = int(os.environ.get("HONCHO_MIGRATION_DOC_MAX_CHARS", "24000"))
# llama.cpp embedding failures report physical batch/ubatch token limits, not
# just the configured context window.  Some stored code/log messages tokenize
# much larger than their character count, so keep halving below this target if
# the endpoint still rejects the truncated prefix.
DOC_MIN_CHARS = int(os.environ.get("HONCHO_MIGRATION_DOC_MIN_CHARS", "512"))
SKIP_RESET = os.environ.get("HONCHO_MIGRATION_SKIP_RESET", "false").lower() == "true"
SKIP_DOCUMENTS = os.environ.get("HONCHO_MIGRATION_SKIP_DOCUMENTS", "false").lower() == "true"


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {message}", flush=True)


def is_embedding_size_error(error: Exception) -> bool:
    message = str(error)
    return "maximum token limit" in message or "too large to process" in message


async def scalar_int(db: AsyncSession, sql: str, params: dict | None = None) -> int:
    row = (await db.execute(text(sql), params or {})).first()
    return int(row[0]) if row is not None else 0


async def embed_truncated_content(content: str, max_chars: int = DOC_MAX_CHARS) -> tuple[list[float], bool]:
    limit = min(len(content), max_chars)
    target_floor = max(1, min(DOC_MIN_CHARS, limit))
    while limit >= 1:
        try:
            return await embedding_client.embed(content[:limit]), limit < len(content)
        except Exception as error:
            if not is_embedding_size_error(error):
                raise
            if limit <= 1:
                raise
            if limit > target_floor:
                limit = max(target_floor, limit // 2)
            else:
                # The endpoint is failing on physical ubatch tokens even below
                # the desired floor; keep shrinking so a pathological single
                # message/document does not abort the whole migration.
                limit = max(1, limit // 2)
    raise RuntimeError("unreachable embedding truncation state")


async def preflight() -> None:
    log("preflight: checking embedding client and current schema")
    sample = await embedding_client.embed("Joy asks Talon to keep memories local.")
    if len(sample) != TARGET_DIM:
        raise RuntimeError(f"embedding endpoint returned dim={len(sample)}, expected {TARGET_DIM}")

    async with tracked_db("local_embedding_migration_preflight") as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT c.relname, a.atttypmod
                    FROM pg_attribute a
                    JOIN pg_class c ON a.attrelid = c.oid
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    WHERE n.nspname = 'public'
                      AND c.relname IN ('documents', 'message_embeddings')
                      AND a.attname = 'embedding'
                    ORDER BY c.relname
                    """
                )
            )
        ).all()
        log(f"preflight: endpoint_dim={len(sample)} schema={[(r[0], r[1]) for r in rows]}")
        messages_with_content = await scalar_int(
            db, "select count(*) from messages where length(trim(content)) > 0"
        )
        log(
            "preflight counts: "
            f"documents={await scalar_int(db, 'select count(*) from documents where deleted_at is null')} "
            f"message_embeddings={await scalar_int(db, 'select count(*) from message_embeddings')} "
            f"messages_with_content={messages_with_content}"
        )


async def reset_schema() -> None:
    log("schema: stopping vector state, dropping HNSW indexes, clearing old vectors, altering to target dimension")
    async with engine.begin() as conn:
        await conn.execute(text("LOCK TABLE public.documents IN ACCESS EXCLUSIVE MODE"))
        await conn.execute(text("LOCK TABLE public.message_embeddings IN ACCESS EXCLUSIVE MODE"))
        await conn.execute(text("DROP INDEX IF EXISTS public.ix_documents_embedding_hnsw"))
        await conn.execute(text("DROP INDEX IF EXISTS public.ix_message_embeddings_embedding_hnsw"))
        await conn.execute(
            text(
                """
                UPDATE public.documents
                SET embedding = NULL,
                    sync_state = 'pending',
                    last_sync_at = NULL,
                    sync_attempts = 0
                WHERE embedding IS NOT NULL
                   OR sync_state <> 'pending'
                   OR last_sync_at IS NOT NULL
                   OR sync_attempts <> 0
                """
            )
        )
        await conn.execute(text("DELETE FROM public.message_embeddings"))
        await conn.execute(
            text(f"ALTER TABLE public.documents ALTER COLUMN embedding TYPE vector({TARGET_DIM}) USING NULL")
        )
        await conn.execute(
            text(f"ALTER TABLE public.message_embeddings ALTER COLUMN embedding TYPE vector({TARGET_DIM}) USING NULL")
        )
    log("schema: reset complete")


async def fetch_document_batch(db: AsyncSession) -> Sequence[models.Document]:
    rows = (
        await db.execute(
            select(models.Document)
            .where(models.Document.deleted_at.is_(None))
            .where(models.Document.embedding.is_(None))
            .where(func.length(func.trim(models.Document.content)) > 0)
            .order_by(models.Document.created_at, models.Document.id)
            .limit(DOC_BATCH_SIZE)
        )
    ).scalars().all()
    return list(rows)


async def embed_documents() -> int:
    log(f"documents: embedding with batch_size={DOC_BATCH_SIZE}")
    total = 0
    truncated = 0
    started = time.monotonic()
    async with tracked_db("local_embedding_migration_documents") as db:
        while True:
            docs = await fetch_document_batch(db)
            if not docs:
                break
            try:
                embeddings = await embedding_client.simple_batch_embed([d.content for d in docs])
            except Exception as e:
                if not is_embedding_size_error(e):
                    raise
                log("documents: batch exceeded embedding size limit; retrying documents individually with truncation")
                embeddings = []
                for doc in docs:
                    embedding, was_truncated = await embed_truncated_content(doc.content)
                    embeddings.append(embedding)
                    if was_truncated:
                        truncated += 1
            if len(embeddings) != len(docs):
                raise RuntimeError(f"document batch returned {len(embeddings)} embeddings for {len(docs)} docs")
            for doc, embedding in zip(docs, embeddings, strict=True):
                await db.execute(
                    update(models.Document)
                    .where(models.Document.id == doc.id)
                    .values(
                        embedding=embedding,
                        sync_state="synced",
                        last_sync_at=func.now(),
                        sync_attempts=0,
                    )
                )
            await db.commit()
            total += len(docs)
            if total == len(docs) or total % (DOC_BATCH_SIZE * 10) == 0:
                log(f"documents: embedded={total} elapsed={time.monotonic() - started:.1f}s")
    log(
        f"documents: complete embedded={total} truncated_overlong={truncated} "
        f"elapsed={time.monotonic() - started:.1f}s"
    )
    return total


async def fetch_message_batch(db: AsyncSession) -> Sequence[models.Message]:
    rows = (
        await db.execute(
            select(models.Message)
            .where(func.length(func.trim(models.Message.content)) > 0)
            .where(
                ~select(models.MessageEmbedding.id)
                .where(models.MessageEmbedding.message_id == models.Message.public_id)
                .exists()
            )
            .order_by(models.Message.id)
            .limit(MESSAGE_BATCH_SIZE)
        )
    ).scalars().all()
    return list(rows)


async def embed_messages() -> int:
    log(f"messages: embedding with batch_size={MESSAGE_BATCH_SIZE}")
    total_messages = 0
    total_embeddings = 0
    truncated_messages = 0
    started = time.monotonic()
    async with tracked_db("local_embedding_migration_messages") as db:
        while True:
            messages = await fetch_message_batch(db)
            if not messages:
                break
            id_to_content = {m.public_id: m.content for m in messages if m.content and m.content.strip()}
            try:
                embedded = await embedding_client.batch_embed(id_to_content)
            except Exception as e:
                if not is_embedding_size_error(e):
                    raise
                log("messages: batch exceeded embedding size limit; retrying messages individually with truncation")
                embedded = {}
                for public_id, content in id_to_content.items():
                    embedding, was_truncated = await embed_truncated_content(content)
                    embedded[public_id] = [embedding]
                    if was_truncated:
                        truncated_messages += 1
            objects: list[models.MessageEmbedding] = []
            for message in messages:
                for embedding in embedded.get(message.public_id, []):
                    objects.append(
                        models.MessageEmbedding(
                            content=message.content,
                            embedding=embedding,
                            message_id=message.public_id,
                            workspace_name=message.workspace_name,
                            session_name=message.session_name,
                            peer_name=message.peer_name,
                            sync_state="synced",
                            last_sync_at=func.now(),
                            sync_attempts=0,
                        )
                    )
            if objects:
                db.add_all(objects)
            await db.commit()
            total_messages += len(messages)
            total_embeddings += len(objects)
            if total_messages == len(messages) or total_messages % (MESSAGE_BATCH_SIZE * 10) == 0:
                log(
                    f"messages: messages={total_messages} embeddings={total_embeddings} "
                    f"elapsed={time.monotonic() - started:.1f}s"
                )
    log(
        f"messages: complete messages={total_messages} embeddings={total_embeddings} "
        f"truncated_overlong={truncated_messages} elapsed={time.monotonic() - started:.1f}s"
    )
    return total_embeddings


async def recreate_indexes_and_verify() -> None:
    log("indexes: creating HNSW indexes")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_embedding_hnsw
                ON public.documents USING hnsw (embedding vector_cosine_ops)
                WITH (m='16', ef_construction='64')
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_message_embeddings_embedding_hnsw
                ON public.message_embeddings USING hnsw (embedding vector_cosine_ops)
                WITH (m='16', ef_construction='64')
                """
            )
        )
        await conn.execute(text("ANALYZE public.documents"))
        await conn.execute(text("ANALYZE public.message_embeddings"))

    async with tracked_db("local_embedding_migration_verify") as db:
        dims = (
            await db.execute(
                text(
                    """
                    SELECT c.relname, a.atttypmod
                    FROM pg_attribute a
                    JOIN pg_class c ON a.attrelid = c.oid
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    WHERE n.nspname = 'public'
                      AND c.relname IN ('documents', 'message_embeddings')
                      AND a.attname = 'embedding'
                    ORDER BY c.relname
                    """
                )
            )
        ).all()
        counts = {
            "document_embeddings": await scalar_int(db, "select count(*) from documents where embedding is not null and deleted_at is null"),
            "message_embeddings": await scalar_int(db, "select count(*) from message_embeddings where embedding is not null"),
            "pending_document_vectors": await scalar_int(db, "select count(*) from documents where deleted_at is null and length(trim(content)) > 0 and embedding is null"),
            "messages_without_embeddings": await scalar_int(
                db,
                """
                select count(*)
                from messages m
                where length(trim(m.content)) > 0
                  and not exists (
                    select 1 from message_embeddings e where e.message_id = m.public_id
                  )
                """,
            ),
        }
        log(f"verify: schema={[(r[0], r[1]) for r in dims]} counts={counts}")
        if any(dim != TARGET_DIM for _, dim in dims):
            raise RuntimeError(f"schema dimension mismatch: {dims}")
        if counts["pending_document_vectors"] or counts["messages_without_embeddings"]:
            raise RuntimeError(f"embedding population incomplete: {counts}")


async def main() -> None:
    started = time.monotonic()
    await preflight()
    if SKIP_RESET:
        log("schema: reset skipped by HONCHO_MIGRATION_SKIP_RESET=true")
    else:
        await reset_schema()
    if SKIP_DOCUMENTS:
        log("documents: skipped by HONCHO_MIGRATION_SKIP_DOCUMENTS=true")
    else:
        await embed_documents()
    await embed_messages()
    await recreate_indexes_and_verify()
    log(f"migration complete total_elapsed={time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
