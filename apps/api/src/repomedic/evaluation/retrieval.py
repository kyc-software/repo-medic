"""Deterministic retrieval and citation metrics."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from repomedic.domain.models import EvidenceItem, ResolutionBrief


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    query: str
    relevant_source_ids: tuple[str, ...]


def retrieval_metrics(
    cases: Sequence[RetrievalCase], rankings: Mapping[str, Sequence[str]], cutoff: int = 3
) -> dict[str, float]:
    if not cases:
        raise ValueError("at least one retrieval case is required")
    hits = 0
    reciprocal_ranks = 0.0
    for case in cases:
        ranked = rankings.get(case.case_id, ())
        relevant = set(case.relevant_source_ids)
        matches = [
            any(
                source_id == expected or source_id.startswith(f"{expected}#")
                for expected in relevant
            )
            for source_id in ranked
        ]
        if any(matches[:cutoff]):
            hits += 1
        first_rank = next((rank for rank, match in enumerate(matches, start=1) if match), None)
        if first_rank is not None:
            reciprocal_ranks += 1 / first_rank
    return {"hit_at_3": hits / len(cases), "mrr": reciprocal_ranks / len(cases)}


def citation_metrics(brief: ResolutionBrief, evidence: Sequence[EvidenceItem]) -> dict[str, float]:
    available = {item.source_id for item in evidence}
    cited = set(brief.citation_ids)
    cited.update(citation for step in brief.investigation_steps for citation in step.citation_ids)
    citation_validity = 1.0 if cited and cited <= available else 0.0
    unsupported_steps = sum(not step.citation_ids for step in brief.investigation_steps)
    unsupported_rate = unsupported_steps / max(len(brief.investigation_steps), 1)
    return {
        "citation_presence": float(bool(cited)),
        "citation_validity": citation_validity,
        "unsupported_claim_rate": unsupported_rate,
    }
