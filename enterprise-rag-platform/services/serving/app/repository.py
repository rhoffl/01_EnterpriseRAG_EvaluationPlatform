from openai import AsyncOpenAI
from psycopg import AsyncConnection
from rag_core.config import get_settings
from rag_core.contracts import ChunkRecord, Principal
from rag_core.retrieval import reciprocal_rank_fusion


async def embed_query(question: str) -> list[float]:
    settings = get_settings()
    if not settings.openai_api_key:
        return [0.0] * 1536
    response = await AsyncOpenAI(api_key=settings.openai_api_key).embeddings.create(
        model=settings.embedding_model, input=[question]
    )
    return response.data[0].embedding


async def retrieve(
    principal: Principal, question: str, mode: str, limit: int = 8
) -> list[ChunkRecord]:
    settings = get_settings()
    query_vector = await embed_query(question) if mode in {"vector", "hybrid"} else None
    lexical: list[tuple] = []
    vector: list[tuple] = []
    params = (principal.tenant_id, principal.roles)
    async with await AsyncConnection.connect(settings.database_url) as connection:
        async with connection.cursor() as cursor:
            if mode in {"lexical", "hybrid"}:
                await cursor.execute(
                    """SELECT c.id,c.document_id,c.document_version_id,c.content,d.title,c.page_start,c.page_end,
                              c.metadata,ts_rank_cd(c.search_vector,websearch_to_tsquery('english',%s)) score
                       FROM chunks c JOIN documents d ON d.id=c.document_id
                       WHERE c.tenant_id=%s AND c.document_version_id=d.active_version_id
                         AND EXISTS (SELECT 1 FROM document_acl a WHERE a.document_id=d.id AND a.role_name=ANY(%s))
                         AND c.search_vector @@ websearch_to_tsquery('english',%s)
                       ORDER BY score DESC LIMIT 40""",
                    (question, *params, question),
                )
                lexical = await cursor.fetchall()
            if mode in {"vector", "hybrid"}:
                await cursor.execute(
                    """SELECT c.id,c.document_id,c.document_version_id,c.content,d.title,c.page_start,c.page_end,
                              c.metadata,1-(c.embedding <=> %s::vector) score
                       FROM chunks c JOIN documents d ON d.id=c.document_id
                       WHERE c.tenant_id=%s AND c.document_version_id=d.active_version_id
                         AND EXISTS (SELECT 1 FROM document_acl a WHERE a.document_id=d.id AND a.role_name=ANY(%s))
                       ORDER BY c.embedding <=> %s::vector LIMIT 40""",
                    (str(query_vector), *params, str(query_vector)),
                )
                vector = await cursor.fetchall()
    rows = {str(row[0]): row for row in lexical + vector}
    if mode == "hybrid":
        fused = reciprocal_rank_fusion([[str(r[0]) for r in lexical], [str(r[0]) for r in vector]])
        ranked = [(rows[item_id], score) for item_id, score in fused[:limit]]
    else:
        selected = lexical if mode == "lexical" else vector
        ranked = [(row, float(row[8])) for row in selected[:limit]]
    return [
        ChunkRecord(
            id=row[0],
            document_id=row[1],
            document_version_id=row[2],
            content=row[3],
            title=row[4],
            page_start=row[5],
            page_end=row[6],
            section_path=row[7].get("section_path", []),
            metadata=row[7],
            score=score,
        )
        for row, score in ranked
    ]
