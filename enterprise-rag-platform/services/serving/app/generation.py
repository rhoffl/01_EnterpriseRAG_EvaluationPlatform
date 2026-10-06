import json

from openai import AsyncOpenAI
from rag_core.citations import validate_citations
from rag_core.config import get_settings
from rag_core.contracts import ChunkRecord, Claim
from rag_core.retrieval import lexical_overlap_score


async def answer_with_evidence(
    question: str, chunks: list[ChunkRecord]
) -> tuple[str, list[Claim], bool, str | None, float]:
    if not chunks or max(lexical_overlap_score(question, c.content) for c in chunks) < 0.05:
        return (
            "I could not find sufficient authorized evidence to answer that question.",
            [],
            True,
            "insufficient_evidence",
            0.0,
        )
    settings = get_settings()
    if not settings.openai_api_key:
        top = chunks[0]
        claim = Claim(text=top.content[:500], citations=["E1"])
        return claim.text, [claim], False, None, 0.0
    evidence = "\n\n".join(
        f"[E{i}] {c.title}, page {c.page_start}\n{c.content}" for i, c in enumerate(chunks, 1)
    )
    response = await AsyncOpenAI(api_key=settings.openai_api_key).chat.completions.create(
        model=settings.chat_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Answer only from evidence. Return JSON with answer and claims; every claim has text and citations. If unsupported, set abstained=true.",
            },
            {"role": "user", "content": f"Question: {question}\n\nEvidence:\n{evidence}"},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    claims = [Claim.model_validate(item) for item in payload.get("claims", [])]
    errors = validate_citations(claims, {f"E{i}" for i in range(1, len(chunks) + 1)})
    if errors:
        return (
            "I could not produce a fully supported answer.",
            [],
            True,
            "citation_validation_failed",
            0.0,
        )
    usage = response.usage
    estimated_cost = (
        ((usage.prompt_tokens * 0.0004) + (usage.completion_tokens * 0.0016)) / 1000
        if usage
        else 0.0
    )
    return (
        payload.get("answer", ""),
        claims,
        bool(payload.get("abstained", False)),
        payload.get("abstention_reason"),
        estimated_cost,
    )
