"""Lifecycle and review rules, kept independent from frameworks and LLMs."""

from dataclasses import dataclass

from repomedic.domain.models import EvidenceItem, PredictionBundle, ResolutionBrief


class DomainConflictError(Exception):
    """Requested transition conflicts with current lifecycle state."""


class InvalidCitationError(Exception):
    """Brief references evidence not attached to its run."""


def validate_citations(brief: ResolutionBrief, evidence: tuple[EvidenceItem, ...]) -> None:
    available = {item.source_id for item in evidence}
    cited = set(brief.citation_ids)
    cited.update(citation for step in brief.investigation_steps for citation in step.citation_ids)
    unknown = cited - available
    if unknown:
        raise InvalidCitationError(f"unknown citation IDs: {', '.join(sorted(unknown))}")


@dataclass(frozen=True)
class ReviewPolicy:
    minimum_confidence: float = 0.72
    minimum_evidence: int = 2

    def reasons(
        self,
        prediction: PredictionBundle,
        evidence: tuple[EvidenceItem, ...],
        brief: ResolutionBrief,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if prediction.calibrated_confidence < self.minimum_confidence:
            reasons.append("prediction_confidence_below_threshold")
        if len(evidence) < self.minimum_evidence:
            reasons.append("insufficient_evidence")
        try:
            validate_citations(brief, evidence)
        except InvalidCitationError:
            reasons.append("invalid_citation_membership")
        return tuple(reasons)
