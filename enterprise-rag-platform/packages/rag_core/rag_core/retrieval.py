from collections.abc import Iterable


def reciprocal_rank_fusion(
    ranked_lists: Iterable[list[str]], *, k: int = 60
) -> list[tuple[str, float]]:
    """Fuse rankings without assuming their raw scores share a scale."""
    scores: dict[str, float] = {}
    for ranking in ranked_lists:
        for rank, document_id in enumerate(ranking, start=1):
            scores[document_id] = scores.get(document_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def lexical_overlap_score(query: str, passage: str) -> float:
    query_terms = {t.casefold() for t in query.split() if len(t) > 2}
    if not query_terms:
        return 0.0
    passage_terms = {t.casefold().strip(".,:;!?()[]") for t in passage.split()}
    return len(query_terms & passage_terms) / len(query_terms)
