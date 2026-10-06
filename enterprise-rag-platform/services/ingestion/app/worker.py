import hashlib
import json
from pathlib import Path
from typing import ClassVar
from uuid import UUID, uuid4

from arq.connections import RedisSettings
from arq.cron import cron
from openai import AsyncOpenAI
from psycopg import AsyncConnection
from rag_core.config import get_settings

from .acquisition import acquire_source, refresh_due_sources
from .chunking import chunk_blocks
from .parser import parse_document


async def _embeddings(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if not settings.openai_api_key:
        # Development fallback; production startup checks should reject this mode.
        return [[0.0] * 1536 for _ in texts]
    result = await AsyncOpenAI(api_key=settings.openai_api_key).embeddings.create(
        model=settings.embedding_model, input=texts
    )
    return [item.embedding for item in result.data]


async def ingest_document(ctx: dict, job: dict) -> dict:
    settings = get_settings()
    job_id = UUID(job["job_id"])
    document_id = UUID(job["document_id"])
    path = Path(job["path"])
    raw = path.read_bytes()
    blocks = parse_document(path, job.get("content_type"))
    chunks = chunk_blocks(blocks, job["chunk_size"], job["chunk_overlap"])
    vectors = await _embeddings([chunk.content for chunk in chunks])
    version_id = uuid4()
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE ingestion_jobs SET status='processing' WHERE id=%s", (job_id,)
            )
            await cursor.execute(
                "SELECT 1 FROM document_versions WHERE document_id=%s AND content_hash=%s",
                (document_id, hashlib.sha256(raw).hexdigest()),
            )
            if await cursor.fetchone():
                await cursor.execute(
                    "UPDATE ingestion_jobs SET status='skipped', completed_at=now() WHERE id=%s",
                    (job_id,),
                )
                await connection.commit()
                return {"job_id": str(job_id), "status": "skipped", "reason": "duplicate"}
            await cursor.execute(
                """INSERT INTO document_versions
                   (id, document_id, version_number, content_hash, parser_version, chunker_config, status)
                   VALUES (%s, %s, COALESCE((SELECT max(version_number)+1 FROM document_versions WHERE document_id=%s),1),
                           %s, '1.0', %s, 'indexing')""",
                (
                    version_id,
                    document_id,
                    document_id,
                    hashlib.sha256(raw).hexdigest(),
                    json.dumps({"size": job["chunk_size"], "overlap": job["chunk_overlap"]}),
                ),
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                await cursor.execute(
                    """INSERT INTO chunks
                       (id, tenant_id, document_id, document_version_id, chunk_index, content,
                        metadata, page_start, page_end, token_count, embedding, search_vector)
                       SELECT %s, d.tenant_id, d.id, %s, %s, %s, %s, %s, %s, %s, %s::vector,
                              to_tsvector('english', %s)
                       FROM documents d WHERE d.id=%s""",
                    (
                        uuid4(),
                        version_id,
                        index,
                        chunk.content,
                        json.dumps({"section_path": chunk.section_path}),
                        chunk.page_start,
                        chunk.page_end,
                        chunk.token_count,
                        str(vector),
                        chunk.content,
                        document_id,
                    ),
                )
            await cursor.execute(
                "UPDATE document_versions SET status='active' WHERE id=%s", (version_id,)
            )
            await cursor.execute(
                "UPDATE documents SET active_version_id=%s WHERE id=%s", (version_id, document_id)
            )
            await cursor.execute(
                "UPDATE ingestion_jobs SET status='completed', completed_at=now() WHERE id=%s",
                (job_id,),
            )
        await connection.commit()
    return {"job_id": str(job_id), "chunks": len(chunks), "version_id": str(version_id)}


class WorkerSettings:
    functions: ClassVar = [ingest_document, acquire_source, refresh_due_sources]
    cron_jobs: ClassVar = [cron(refresh_due_sources, minute=0)]
    redis_settings: ClassVar = RedisSettings.from_dsn(get_settings().redis_url)
