import pytest
from rag_core.metrics import cost_per_success, mean_reciprocal_rank, ndcg_at_k, recall_at_k


def test_retrieval_metrics():
    rankings = [["x", "a", "b"], ["c", "d", "z"]]
    relevant = [{"a"}, {"z"}]
    assert recall_at_k(rankings, relevant, 2) == 0.5
    assert recall_at_k(rankings, relevant, 3) == 1.0
    assert mean_reciprocal_rank(rankings, relevant) == pytest.approx((1 / 2 + 1 / 3) / 2)


def test_ndcg_and_cost():
    assert ndcg_at_k([["a", "b"]], [{"a": 3, "b": 1}], 2) == 1.0
    assert cost_per_success(1.25, 5) == 0.25
    assert cost_per_success(1.25, 0) is None
