from .contracts import Claim


def validate_citations(claims: list[Claim], allowed_evidence_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for index, claim in enumerate(claims):
        if not claim.citations:
            errors.append(f"claim[{index}] has no citation")
        unknown = set(claim.citations) - allowed_evidence_ids
        if unknown:
            errors.append(f"claim[{index}] cites unknown evidence: {sorted(unknown)}")
    return errors
