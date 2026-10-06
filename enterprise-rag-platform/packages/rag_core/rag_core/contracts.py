from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Principal(BaseModel):
    subject: str
    tenant_id: UUID
    roles: list[str] = Field(default_factory=list)


class ChunkRecord(BaseModel):
    id: UUID
    document_id: UUID
    document_version_id: UUID
    content: str
    title: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0


class Citation(BaseModel):
    evidence_id: str
    document_id: UUID
    title: str
    page_start: int | None = None
    page_end: int | None = None
    quote: str


class Claim(BaseModel):
    text: str
    citations: list[str]


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=20)
    retrieval_mode: Literal["lexical", "vector", "hybrid"] = "hybrid"


class QueryResponse(BaseModel):
    answer: str
    claims: list[Claim]
    citations: list[Citation]
    abstained: bool
    abstention_reason: str | None = None
    trace_id: UUID
    latency_ms: dict[str, float]
    estimated_cost_usd: float
