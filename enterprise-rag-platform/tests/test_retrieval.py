from rag_core.retrieval import lexical_overlap_score, reciprocal_rank_fusion


def test_rrf_rewards_items_present_in_both_rankings():
    result = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d", "a"]])
    assert result[0][0] in {"a", "b"}
    scores = dict(result)
    assert scores["a"] > scores["c"]
    assert scores["b"] > scores["d"]


def test_lexical_overlap_is_bounded():
    score = lexical_overlap_score(
        "audit log retention", "The audit log retention period is seven years."
    )
    assert 0 < score <= 1
