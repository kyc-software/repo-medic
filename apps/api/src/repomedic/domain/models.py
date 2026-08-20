"""Public domain contracts. Illegal lifecycle combinations are separate models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IssueSubmission(DomainModel):
    client_request_id: str = Field(min_length=8, max_length=100)
    title: str = Field(min_length=4, max_length=300)
    body: str = Field(min_length=10, max_length=20_000)

    @field_validator("client_request_id", "title", "body")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class RunningPhase(StrEnum):
    PREDICTING = "predicting"
    RETRIEVING = "retrieving"
    INVESTIGATING = "investigating"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"


class IssueType(StrEnum):
    BUG = "bug"
    DOCUMENTATION = "documentation"
    FEATURE = "feature"
    QUESTION = "question"


class PredictionBundle(DomainModel):
    issue_type: IssueType
    calibrated_confidence: float = Field(ge=0, le=1)
    predicted_close_days: float = Field(ge=0)
    classifier_version: str
    regressor_version: str


class SourceKind(StrEnum):
    DOCUMENTATION = "documentation"
    CODE = "code"
    RESOLVED_ISSUE = "resolved_issue"


class EvidenceItem(DomainModel):
    source_id: str
    source_kind: SourceKind
    url: HttpUrl
    repository_sha: str
    excerpt: str
    score: float = Field(ge=0, le=1)
    path: str | None = None
    issue_number: int | None = None

    @field_validator("repository_sha")
    @classmethod
    def valid_sha(cls, value: str) -> str:
        if len(value) < 7:
            raise ValueError("repository SHA must contain at least seven characters")
        return value


class InvestigationStep(DomainModel):
    rank: int = Field(ge=1)
    action: str
    rationale: str
    citation_ids: tuple[str, ...]


class ResolutionBrief(DomainModel):
    summary: str
    investigation_steps: tuple[InvestigationStep, ...]
    missing_information: tuple[str, ...]
    citation_ids: tuple[str, ...]


class QueuedRun(DomainModel):
    status: Literal["queued"] = "queued"
    run_id: UUID
    submission: IssueSubmission
    created_at: datetime


class RunningRun(DomainModel):
    status: Literal["running"] = "running"
    run_id: UUID
    submission: IssueSubmission
    phase: RunningPhase
    created_at: datetime
    updated_at: datetime


class AwaitingReviewRun(DomainModel):
    status: Literal["awaiting_review"] = "awaiting_review"
    run_id: UUID
    submission: IssueSubmission
    prediction: PredictionBundle
    evidence: tuple[EvidenceItem, ...]
    draft: ResolutionBrief
    review_reasons: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


class CompletedRun(DomainModel):
    status: Literal["completed"] = "completed"
    run_id: UUID
    submission: IssueSubmission
    prediction: PredictionBundle
    evidence: tuple[EvidenceItem, ...]
    brief: ResolutionBrief
    created_at: datetime
    updated_at: datetime


class RejectedRun(DomainModel):
    status: Literal["rejected"] = "rejected"
    run_id: UUID
    submission: IssueSubmission
    reason: str
    created_at: datetime
    updated_at: datetime


class FailedRun(DomainModel):
    status: Literal["failed"] = "failed"
    run_id: UUID
    submission: IssueSubmission
    error_code: str
    retryable: bool
    created_at: datetime
    updated_at: datetime


TriageRunSnapshot = Annotated[
    QueuedRun | RunningRun | AwaitingReviewRun | CompletedRun | RejectedRun | FailedRun,
    Field(discriminator="status"),
]


class ApproveDecision(DomainModel):
    kind: Literal["approve"] = "approve"


class EditDecision(DomainModel):
    kind: Literal["edit"] = "edit"
    brief: ResolutionBrief


class RejectDecision(DomainModel):
    kind: Literal["reject"] = "reject"
    reason: str = Field(min_length=3, max_length=1_000)


ReviewDecision = Annotated[
    ApproveDecision | EditDecision | RejectDecision, Field(discriminator="kind")
]


class EventKind(StrEnum):
    RUN_QUEUED = "run.queued"
    RUN_PHASE = "run.phase"
    REVIEW_REQUIRED = "review.required"
    RUN_COMPLETED = "run.completed"
    RUN_REJECTED = "run.rejected"
    RUN_FAILED = "run.failed"


class RunEventBase(DomainModel):
    sequence: int = Field(ge=1)
    run_id: UUID
    timestamp: datetime


class QueuedEventPayload(DomainModel):
    status: Literal["queued"] = "queued"


class PhaseEventPayload(DomainModel):
    phase: RunningPhase
    snapshot: RunningRun


class ReviewEventPayload(DomainModel):
    snapshot: AwaitingReviewRun


class CompletedEventPayload(DomainModel):
    snapshot: CompletedRun


class RejectedEventPayload(DomainModel):
    snapshot: RejectedRun


class FailedEventPayload(DomainModel):
    snapshot: FailedRun


class RunQueuedEvent(RunEventBase):
    kind: Literal[EventKind.RUN_QUEUED]
    payload: QueuedEventPayload


class RunPhaseEvent(RunEventBase):
    kind: Literal[EventKind.RUN_PHASE]
    payload: PhaseEventPayload


class ReviewRequiredEvent(RunEventBase):
    kind: Literal[EventKind.REVIEW_REQUIRED]
    payload: ReviewEventPayload


class RunCompletedEvent(RunEventBase):
    kind: Literal[EventKind.RUN_COMPLETED]
    payload: CompletedEventPayload


class RunRejectedEvent(RunEventBase):
    kind: Literal[EventKind.RUN_REJECTED]
    payload: RejectedEventPayload


class RunFailedEvent(RunEventBase):
    kind: Literal[EventKind.RUN_FAILED]
    payload: FailedEventPayload


RunEvent = Annotated[
    RunQueuedEvent
    | RunPhaseEvent
    | ReviewRequiredEvent
    | RunCompletedEvent
    | RunRejectedEvent
    | RunFailedEvent,
    Field(discriminator="kind"),
]


def now_utc() -> datetime:
    return datetime.now(UTC)
