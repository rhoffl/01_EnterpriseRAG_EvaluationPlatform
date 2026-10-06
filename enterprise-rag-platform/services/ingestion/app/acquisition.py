import hashlib
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import httpx
from psycopg import AsyncConnection
from rag_core.config import get_settings

CONTENT_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/json": ".json",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


def validate_source_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("source URL must be an unauthenticated HTTPS URL")
    if host not in allowed_hosts:
        raise ValueError(f"source host is not allowlisted: {host}")
    return host


def _ensure_public_host(host: str) -> None:
    for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(result[4][0])
        if not address.is_global:
            raise ValueError("source host resolved to a non-public address")


async def download_source(url: str) -> tuple[bytes, str, int, str]:
    settings = get_settings()
    allowed = {host.strip().lower() for host in settings.acquisition_allowed_hosts.split(",")}
    current_url = url
    async with httpx.AsyncClient(timeout=settings.acquisition_timeout_seconds) as client:
        for _ in range(4):
            host = validate_source_url(current_url, allowed)
            _ensure_public_host(host)
            async with client.stream("GET", current_url, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect did not provide a location")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > settings.acquisition_max_bytes:
                    raise ValueError("source exceeds maximum permitted size")
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > settings.acquisition_max_bytes:
                        raise ValueError("source exceeds maximum permitted size")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                extension = CONTENT_EXTENSIONS.get(content_type)
                if not extension:
                    extension = Path(urlparse(current_url).path).suffix.lower()
                if extension not in set(CONTENT_EXTENSIONS.values()):
                    raise ValueError(
                        f"unsupported acquired content type: {content_type or extension}"
                    )
                return bytes(body), content_type, response.status_code, extension
    raise ValueError("too many redirects")


async def acquire_source(ctx: dict, job: dict) -> dict:
    settings = get_settings()
    run_id, source_id, tenant_id = map(UUID, (job["run_id"], job["source_id"], job["tenant_id"]))
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE acquisition_runs SET status='processing', started_at=now() WHERE id=%s",
                (run_id,),
            )
            await cursor.execute(
                """SELECT name, url, document_type, allowed_roles, metadata
                   FROM source_registry WHERE id=%s AND tenant_id=%s AND enabled""",
                (source_id, tenant_id),
            )
            source = await cursor.fetchone()
        await connection.commit()
    if not source:
        raise ValueError("enabled source not found")

    title, url, document_type, roles, metadata = source
    try:
        payload, content_type, http_status, extension = await download_source(url)
        digest = hashlib.sha256(payload).hexdigest()
        async with await AsyncConnection.connect(settings.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT 1 FROM source_snapshots WHERE source_registry_id=%s AND content_hash=%s",
                    (source_id, digest),
                )
                if await cursor.fetchone():
                    await cursor.execute(
                        """UPDATE acquisition_runs SET status='skipped', http_status=%s,
                           content_hash=%s, bytes_downloaded=%s, completed_at=now() WHERE id=%s""",
                        (http_status, digest, len(payload), run_id),
                    )
                    await cursor.execute(
                        """UPDATE source_registry SET last_checked_at=now(),
                           next_refresh_at=now() + make_interval(hours => refresh_interval_hours),
                           updated_at=now() WHERE id=%s""",
                        (source_id,),
                    )
                    await connection.commit()
                    return {"run_id": str(run_id), "status": "skipped", "reason": "unchanged"}

                await cursor.execute(
                    "SELECT id FROM documents WHERE tenant_id=%s AND source_registry_id=%s",
                    (tenant_id, source_id),
                )
                row = await cursor.fetchone()
                document_id = row[0] if row else uuid4()
                if not row:
                    await cursor.execute(
                        """INSERT INTO documents
                           (id, tenant_id, title, source_type, source_uri, source_registry_id)
                           VALUES(%s,%s,%s,%s,%s,%s)""",
                        (document_id, tenant_id, title, document_type, url, source_id),
                    )
                    await cursor.execute(
                        "INSERT INTO document_acl(document_id, role_name) SELECT %s, unnest(%s::text[])",
                        (document_id, roles),
                    )
                object_path = (
                    Path(settings.object_store_path)
                    / str(tenant_id)
                    / str(document_id)
                    / f"{digest}{extension}"
                )
                object_path.parent.mkdir(parents=True, exist_ok=True)
                object_path.write_bytes(payload)
                ingestion_job_id = uuid4()
                await cursor.execute(
                    """INSERT INTO ingestion_jobs(id, document_id, status, file_hash)
                       VALUES(%s,%s,'queued',%s)""",
                    (ingestion_job_id, document_id, digest),
                )
                await cursor.execute(
                    """INSERT INTO source_snapshots
                       (id, source_registry_id, document_id, ingestion_job_id, content_hash,
                        source_url, object_path) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        uuid4(),
                        source_id,
                        document_id,
                        ingestion_job_id,
                        digest,
                        url,
                        str(object_path),
                    ),
                )
                await cursor.execute(
                    """UPDATE acquisition_runs SET status='downloaded', http_status=%s,
                       content_hash=%s, bytes_downloaded=%s, ingestion_job_id=%s,
                       completed_at=now() WHERE id=%s""",
                    (http_status, digest, len(payload), ingestion_job_id, run_id),
                )
                await cursor.execute(
                    """UPDATE source_registry SET last_checked_at=now(), last_success_at=now(),
                       next_refresh_at=now() + make_interval(hours => refresh_interval_hours),
                       updated_at=now() WHERE id=%s""",
                    (source_id,),
                )
            await connection.commit()
        await ctx["redis"].enqueue_job(
            "ingest_document",
            {
                "job_id": str(ingestion_job_id),
                "document_id": str(document_id),
                "path": str(object_path),
                "content_type": content_type,
                "chunk_size": int(metadata.get("chunk_size", 500)),
                "chunk_overlap": int(metadata.get("chunk_overlap", 75)),
            },
        )
        return {"run_id": str(run_id), "status": "downloaded", "job_id": str(ingestion_job_id)}
    except Exception as exc:
        async with await AsyncConnection.connect(settings.database_url) as connection:
            await connection.execute(
                """UPDATE acquisition_runs SET status='failed', error_message=%s,
                   completed_at=now() WHERE id=%s""",
                (str(exc)[:2000], run_id),
            )
            await connection.execute(
                """UPDATE source_registry SET last_checked_at=now(),
                   next_refresh_at=now() + interval '24 hours', updated_at=now() WHERE id=%s""",
                (source_id,),
            )
            await connection.commit()
        raise


async def refresh_due_sources(ctx: dict) -> dict:
    settings = get_settings()
    queued = 0
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """SELECT id, tenant_id FROM source_registry
                   WHERE enabled AND next_refresh_at <= now()
                     AND NOT EXISTS (
                       SELECT 1 FROM acquisition_runs r
                       WHERE r.source_registry_id=source_registry.id
                         AND r.status IN ('queued','processing')
                     )
                   ORDER BY next_refresh_at LIMIT 100"""
            )
            sources = await cursor.fetchall()
            for source_id, tenant_id in sources:
                run_id = uuid4()
                await cursor.execute(
                    """INSERT INTO acquisition_runs(id, tenant_id, source_registry_id, status)
                       VALUES(%s,%s,%s,'queued')""",
                    (run_id, tenant_id, source_id),
                )
                await ctx["redis"].enqueue_job(
                    "acquire_source",
                    {
                        "run_id": str(run_id),
                        "source_id": str(source_id),
                        "tenant_id": str(tenant_id),
                    },
                )
                queued += 1
        await connection.commit()
    return {"queued": queued}
