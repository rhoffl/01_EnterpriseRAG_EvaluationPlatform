import os
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rag_core.contracts import Citation, Principal, QueryRequest, QueryResponse

from .auth import current_principal
from .evaluation import EvaluationRequest, score_retrieval
from .generation import answer_with_evidence
from .repository import retrieve

app = FastAPI(title="RAG Serving and Evaluation Service", version="0.1.0")
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "serving"}


@app.post("/v1/query", response_model=QueryResponse)
async def query(
    request: QueryRequest, principal: Principal = Depends(current_principal)
) -> QueryResponse:
    started = perf_counter()
    retrieval_started = perf_counter()
    chunks = await retrieve(principal, request.question, request.retrieval_mode, request.top_k)
    retrieval_ms = (perf_counter() - retrieval_started) * 1000
    generation_started = perf_counter()
    answer, claims, abstained, reason, cost = await answer_with_evidence(request.question, chunks)
    generation_ms = (perf_counter() - generation_started) * 1000
    citations = [
        Citation(
            evidence_id=f"E{i}",
            document_id=c.document_id,
            title=c.title,
            page_start=c.page_start,
            page_end=c.page_end,
            quote=c.content[:700],
        )
        for i, c in enumerate(chunks, 1)
    ]
    return QueryResponse(
        answer=answer,
        claims=claims,
        citations=citations,
        abstained=abstained,
        abstention_reason=reason,
        trace_id=uuid4(),
        latency_ms={
            "retrieval": retrieval_ms,
            "generation": generation_ms,
            "total": (perf_counter() - started) * 1000,
        },
        estimated_cost_usd=cost,
    )


@app.post("/v1/evaluations/score")
async def evaluate(
    request: EvaluationRequest, _: Principal = Depends(current_principal)
) -> dict[str, float]:
    """Score stored or externally produced rankings with deterministic metrics."""
    return score_retrieval(request.cases, request.rankings)
