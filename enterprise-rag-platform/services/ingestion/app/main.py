import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from psycopg import AsyncConnection
from pydantic import BaseModel, Field
from rag_core.config import get_settings

from .acquisition import validate_source_url

app = FastAPI(title="RAG Ingestion Service", version="0.1.0")


class SourceDefinition(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    url: str
    publisher: str = Field(min_length=2, max_length=200)
    authority_tier: str = Field(pattern="^[A-D]$")
    document_type: str = Field(min_length=2, max_length=100)
    allowed_roles: list[str] = Field(default_factory=lambda: ["reader"])
    refresh_interval_hours: int = Field(default=168, ge=1, le=8760)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceManifest(BaseModel):
    sources: list[SourceDefinition] = Field(min_length=1, max_length=500)


class BulkAcquisitionRequest(BaseModel):
    source_ids: list[UUID] | None = None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ingestion"}


@app.post("/v1/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    allowed_roles: str = Form("reader"),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(75),
    x_tenant_id: UUID = Header(...),
) -> dict:
    if chunk_size < 100 or chunk_size > 2000 or chunk_overlap >= chunk_size:
        raise HTTPException(400, "invalid chunk configuration")
    settings = get_settings()
    payload = await file.read()
    digest = hashlib.sha256(payload).hexdigest()
    document_id, job_id = uuid4(), uuid4()
    suffix = Path(file.filename or "document.bin").suffix
    destination = Path(settings.object_store_path) / str(x_tenant_id) / f"{document_id}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    roles = sorted({role.strip() for role in allowed_roles.split(",") if role.strip()})
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """SELECT d.id FROM documents d
                   JOIN document_versions v ON v.document_id=d.id
                   WHERE d.tenant_id=%s AND v.content_hash=%s LIMIT 1""",
                (x_tenant_id, digest),
            )
            duplicate = await cursor.fetchone()
            if duplicate:
                destination.unlink(missing_ok=True)
                return {
                    "document_id": duplicate[0],
                    "job_id": None,
                    "status": "skipped",
                    "reason": "duplicate content already indexed",
                }
            await cursor.execute(
                "INSERT INTO documents(id, tenant_id, title, source_type, source_uri) VALUES(%s,%s,%s,%s,%s)",
                (document_id, x_tenant_id, title, suffix.lstrip("."), str(destination)),
            )
            await cursor.execute(
                "INSERT INTO document_acl(document_id, role_name) SELECT %s, unnest(%s::text[])",
                (document_id, roles),
            )
            await cursor.execute(
                "INSERT INTO ingestion_jobs(id, document_id, status, file_hash) VALUES(%s,%s,'queued',%s)",
                (job_id, document_id, digest),
            )
        await connection.commit()
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await redis.enqueue_job(
        "ingest_document",
        {
            "job_id": str(job_id),
            "document_id": str(document_id),
            "path": str(destination),
            "content_type": file.content_type,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        },
    )
    await redis.close()
    return {"document_id": document_id, "job_id": job_id, "status": "queued"}


@app.post("/v1/sources/import")
async def import_sources(
    manifest: SourceManifest, x_tenant_id: UUID = Header(...)
) -> dict[str, Any]:
    settings = get_settings()
    allowed_hosts = {
        host.strip().lower()
        for host in settings.acquisition_allowed_hosts.split(",")
        if host.strip()
    }
    imported: list[dict[str, Any]] = []
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            for source in manifest.sources:
                try:
                    validate_source_url(source.url, allowed_hosts)
                except ValueError as exc:
                    raise HTTPException(400, f"{source.name}: {exc}") from exc
                source_id = uuid4()
                roles = sorted({role.strip() for role in source.allowed_roles if role.strip()})
                if not roles:
                    raise HTTPException(400, f"{source.name}: at least one role is required")
                await cursor.execute(
                    """INSERT INTO source_registry
                       (id, tenant_id, name, url, publisher, authority_tier, document_type,
                        allowed_roles, metadata, enabled, refresh_interval_hours)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(tenant_id, url) DO UPDATE SET
                         name=excluded.name, publisher=excluded.publisher,
                         authority_tier=excluded.authority_tier,
                         document_type=excluded.document_type,
                         allowed_roles=excluded.allowed_roles, metadata=excluded.metadata,
                         enabled=excluded.enabled,
                         refresh_interval_hours=excluded.refresh_interval_hours,
                         updated_at=now()
                       RETURNING id""",
                    (
                        source_id,
                        x_tenant_id,
                        source.name,
                        source.url,
                        source.publisher,
                        source.authority_tier,
                        source.document_type,
                        roles,
                        json.dumps(source.metadata),
                        source.enabled,
                        source.refresh_interval_hours,
                    ),
                )
                actual_id = (await cursor.fetchone())[0]
                imported.append({"id": actual_id, "name": source.name, "url": source.url})
        await connection.commit()
    return {"imported": len(imported), "sources": imported}


@app.get("/v1/sources")
async def list_sources(x_tenant_id: UUID = Header(...)) -> dict[str, Any]:
    settings = get_settings()
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """SELECT id, name, url, publisher, authority_tier, document_type, enabled,
                          refresh_interval_hours, next_refresh_at, last_checked_at, last_success_at
                   FROM source_registry WHERE tenant_id=%s ORDER BY authority_tier, publisher, name""",
                (x_tenant_id,),
            )
            rows = await cursor.fetchall()
    keys = [
        "id",
        "name",
        "url",
        "publisher",
        "authority_tier",
        "document_type",
        "enabled",
        "refresh_interval_hours",
        "next_refresh_at",
        "last_checked_at",
        "last_success_at",
    ]
    return {"sources": [dict(zip(keys, row, strict=True)) for row in rows]}


@app.post("/v1/acquisitions", status_code=202)
async def acquire_sources(
    request: BulkAcquisitionRequest, x_tenant_id: UUID = Header(...)
) -> dict[str, Any]:
    settings = get_settings()
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    runs: list[dict[str, UUID]] = []
    try:
        async with await AsyncConnection.connect(settings.database_url) as connection:
            async with connection.cursor() as cursor:
                if request.source_ids:
                    await cursor.execute(
                        """SELECT id FROM source_registry
                           WHERE tenant_id=%s AND enabled AND id=ANY(%s::uuid[])""",
                        (x_tenant_id, request.source_ids),
                    )
                else:
                    await cursor.execute(
                        "SELECT id FROM source_registry WHERE tenant_id=%s AND enabled",
                        (x_tenant_id,),
                    )
                source_ids = [row[0] for row in await cursor.fetchall()]
                for source_id in source_ids:
                    run_id = uuid4()
                    await cursor.execute(
                        """INSERT INTO acquisition_runs(id, tenant_id, source_registry_id, status)
                           VALUES(%s,%s,%s,'queued')""",
                        (run_id, x_tenant_id, source_id),
                    )
                    await redis.enqueue_job(
                        "acquire_source",
                        {
                            "run_id": str(run_id),
                            "source_id": str(source_id),
                            "tenant_id": str(x_tenant_id),
                        },
                    )
                    runs.append({"run_id": run_id, "source_id": source_id})
            await connection.commit()
    finally:
        await redis.close()
    return {"queued": len(runs), "runs": runs}


@app.get("/v1/acquisition-runs/{run_id}")
async def acquisition_status(run_id: UUID, x_tenant_id: UUID = Header(...)) -> dict[str, Any]:
    settings = get_settings()
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """SELECT status, source_registry_id, ingestion_job_id, http_status, content_hash,
                          bytes_downloaded, error_message, started_at, completed_at
                   FROM acquisition_runs WHERE id=%s AND tenant_id=%s""",
                (run_id, x_tenant_id),
            )
            row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, "acquisition run not found")
    keys = [
        "status",
        "source_id",
        "ingestion_job_id",
        "http_status",
        "content_hash",
        "bytes_downloaded",
        "error",
        "started_at",
        "completed_at",
    ]
    return {"run_id": run_id, **dict(zip(keys, row, strict=True))}


@app.get("/v1/ingestion-jobs/{job_id}")
async def ingestion_status(job_id: UUID, x_tenant_id: UUID = Header(...)) -> dict:
    settings = get_settings()
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """SELECT j.status, j.error_message, j.created_at, j.completed_at
                   FROM ingestion_jobs j JOIN documents d ON d.id=j.document_id
                   WHERE j.id=%s AND d.tenant_id=%s""",
                (job_id, x_tenant_id),
            )
            row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job_id,
        "status": row[0],
        "error": row[1],
        "created_at": row[2],
        "completed_at": row[3],
    }
