from pydantic import BaseModel, Field
from rag_core.metrics import mean_reciprocal_rank, ndcg_at_k, recall_at_k


class EvaluationCase(BaseModel):
    question: str
    relevant_chunk_ids: set[str]
    graded_relevance: dict[str, int] = Field(default_factory=dict)


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase]
    rankings: list[list[str]]


def score_retrieval(cases: list[EvaluationCase], rankings: list[list[str]]) -> dict[str, float]:
    if len(cases) != len(rankings):
        raise ValueError("cases and rankings must have equal length")
    relevant = [case.relevant_chunk_ids for case in cases]
    graded = [
        case.graded_relevance or {item: 1 for item in case.relevant_chunk_ids} for case in cases
    ]
    return {
        "recall_at_5": recall_at_k(rankings, relevant, 5),
        "recall_at_10": recall_at_k(rankings, relevant, 10),
        "mrr": mean_reciprocal_rank(rankings, relevant),
        "ndcg_at_10": ndcg_at_k(rankings, graded, 10),
    }
