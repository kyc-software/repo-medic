"""Deterministic adapters: free, fast, and safe for tests and interview rehearsal."""

import asyncio

from pydantic import HttpUrl

from repomedic.domain.models import (
    EvidenceItem,
    InvestigationStep,
    IssueSubmission,
    IssueType,
    PredictionBundle,
    ResolutionBrief,
    SourceKind,
)


class DemoPredictor:
    async def predict(self, submission: IssueSubmission) -> PredictionBundle:
        await asyncio.sleep(0)
        text = f"{submission.title} {submission.body}".lower()
        issue_type = IssueType.BUG
        if "doc" in text:
            issue_type = IssueType.DOCUMENTATION
        elif "feature" in text or "request" in text:
            issue_type = IssueType.FEATURE
        elif "how" in text or "question" in text:
            issue_type = IssueType.QUESTION
        ambiguous = any(token in text for token in ("unclear", "maybe", "sometimes"))
        return PredictionBundle(
            issue_type=issue_type,
            calibrated_confidence=0.58 if ambiguous else 0.89,
            predicted_close_days=12.0 if issue_type is IssueType.BUG else 7.0,
            classifier_version="demo-tfidf-logreg-v1",
            regressor_version="demo-tfidf-ridge-v1",
        )


class DemoRetriever:
    async def retrieve(self, submission: IssueSubmission) -> tuple[EvidenceItem, ...]:
        await asyncio.sleep(0)
        if "no evidence" in submission.body.lower():
            return ()
        return (
            EvidenceItem(
                source_id="docs-common-pitfalls",
                source_kind=SourceKind.DOCUMENTATION,
                url=HttpUrl("https://scikit-learn.org/stable/common_pitfalls.html"),
                repository_sha="demo0001",
                path="doc/common_pitfalls.rst",
                excerpt=(
                    "Keep preprocessing isolated to training data and use pipelines "
                    "to prevent leakage."
                ),
                score=0.91,
            ),
            EvidenceItem(
                source_id="code-validation",
                source_kind=SourceKind.CODE,
                url=HttpUrl(
                    "https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/utils/validation.py"
                ),
                repository_sha="demo0001",
                path="sklearn/utils/validation.py",
                excerpt=(
                    "Input validation centralizes checks for shape, dtype, finiteness, "
                    "and fitted state."
                ),
                score=0.84,
            ),
            EvidenceItem(
                source_id="issue-28990",
                source_kind=SourceKind.RESOLVED_ISSUE,
                url=HttpUrl("https://github.com/scikit-learn/scikit-learn/issues/28990"),
                repository_sha="demo0001",
                issue_number=28990,
                excerpt=(
                    "A resolved issue showing maintainers request a minimal reproducer "
                    "and environment details."
                ),
                score=0.73,
            ),
        )


class DemoInvestigator:
    async def investigate(
        self, submission: IssueSubmission, evidence: tuple[EvidenceItem, ...]
    ) -> tuple[EvidenceItem, ...]:
        await asyncio.sleep(0)
        return evidence


class DemoResolutionWriter:
    async def draft(
        self,
        submission: IssueSubmission,
        prediction: PredictionBundle,
        evidence: tuple[EvidenceItem, ...],
    ) -> ResolutionBrief:
        await asyncio.sleep(0)
        citations = tuple(item.source_id for item in evidence[:2])
        steps = (
            InvestigationStep(
                rank=1,
                action="Reproduce with the smallest estimator, dataset, and parameter set.",
                rationale="Separates an estimator defect from input or pipeline behavior.",
                citation_ids=citations[:1],
            ),
            InvestigationStep(
                rank=2,
                action="Trace input validation and compare observed shape and dtype.",
                rationale="Validation is the common boundary for actionable failures.",
                citation_ids=citations[1:2],
            ),
        )
        return ResolutionBrief(
            summary=(
                f"Likely {prediction.issue_type.value} report. Verify with a minimal reproducer "
                "before assigning an implementation area."
            ),
            investigation_steps=steps,
            missing_information=("scikit-learn version", "minimal reproducer", "full traceback"),
            citation_ids=citations,
        )
