from rag_core.citations import validate_citations
from rag_core.contracts import Claim


def test_citation_validator_rejects_missing_and_unknown_evidence():
    claims = [Claim(text="one", citations=[]), Claim(text="two", citations=["E9"])]
    errors = validate_citations(claims, {"E1"})
    assert len(errors) == 2
