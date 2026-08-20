from pydantic import HttpUrl
from pytest import raises

from repomedic.domain.models import (
    EvidenceItem,
    InvestigationStep,
    ResolutionBrief,
    SourceKind,
)
from repomedic.domain.policy import InvalidCitationError, validate_citations


def test_rejects_citation_outside_attached_evidence() -> None:
    evidence = (
        EvidenceItem(
            source_id="known",
            source_kind=SourceKind.CODE,
            url=HttpUrl("https://github.com/scikit-learn/scikit-learn"),
            repository_sha="abcdef0",
            path="sklearn/base.py",
            excerpt="Base estimator contract.",
            score=0.8,
        ),
    )
    brief = ResolutionBrief(
        summary="Inspect estimator contract.",
        investigation_steps=(
            InvestigationStep(
                rank=1,
                action="Inspect",
                rationale="Boundary",
                citation_ids=("unknown",),
            ),
        ),
        missing_information=(),
        citation_ids=("known",),
    )

    with raises(InvalidCitationError, match="unknown"):
        validate_citations(brief, evidence)
