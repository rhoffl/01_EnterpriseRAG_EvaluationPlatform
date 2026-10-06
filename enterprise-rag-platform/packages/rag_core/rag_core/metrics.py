from math import log2
from statistics import quantiles


def recall_at_k(retrieved: list[list[str]], relevant: list[set[str]], k: int) -> float:
    if not retrieved:
        return 0.0
    hits = [bool(set(items[:k]) & gold) for items, gold in zip(retrieved, relevant, strict=True)]
    return sum(hits) / len(hits)


def mean_reciprocal_rank(retrieved: list[list[str]], relevant: list[set[str]]) -> float:
    if not retrieved:
        return 0.0
    total = 0.0
    for items, gold in zip(retrieved, relevant, strict=True):
        total += next((1.0 / rank for rank, item in enumerate(items, 1) if item in gold), 0.0)
    return total / len(retrieved)


def ndcg_at_k(retrieved: list[list[str]], relevance: list[dict[str, int]], k: int) -> float:
    def dcg(items: list[str], labels: dict[str, int]) -> float:
        return sum(
            (2 ** labels.get(item, 0) - 1) / log2(rank + 1)
            for rank, item in enumerate(items[:k], 1)
        )

    values = []
    for items, labels in zip(retrieved, relevance, strict=True):
        ideal = sorted(labels, key=labels.get, reverse=True)
        denominator = dcg(ideal, labels)
        values.append(dcg(items, labels) / denominator if denominator else 0.0)
    return sum(values) / len(values) if values else 0.0


def latency_percentiles(values_ms: list[float]) -> dict[str, float]:
    if not values_ms:
        return {"p50": 0.0, "p95": 0.0}
    ordered = sorted(values_ms)
    p50 = ordered[(len(ordered) - 1) // 2]
    p95 = quantiles(ordered, n=100, method="inclusive")[94] if len(ordered) > 1 else ordered[0]
    return {"p50": p50, "p95": p95}


def cost_per_success(total_cost: float, successful_answers: int) -> float | None:
    return total_cost / successful_answers if successful_answers else None
