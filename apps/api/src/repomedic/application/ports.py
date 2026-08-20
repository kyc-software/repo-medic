"""Ports only for external systems or state owners."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from repomedic.domain.models import (
    EventKind,
    EvidenceItem,
    IssueSubmission,
    PredictionBundle,
    ResolutionBrief,
    ReviewDecision,
    RunEvent,
    TriageRunSnapshot,
)


class Predictor(Protocol):
    async def predict(self, submission: IssueSubmission) -> PredictionBundle: ...


class Retriever(Protocol):
    async def retrieve(self, submission: IssueSubmission) -> tuple[EvidenceItem, ...]: ...


class Investigator(Protocol):
    async def investigate(
        self, submission: IssueSubmission, evidence: tuple[EvidenceItem, ...]
    ) -> tuple[EvidenceItem, ...]: ...


class ResolutionWriter(Protocol):
    async def draft(
        self,
        submission: IssueSubmission,
        prediction: PredictionBundle,
        evidence: tuple[EvidenceItem, ...],
    ) -> ResolutionBrief: ...


@dataclass(frozen=True)
class WorkflowResult:
    prediction: PredictionBundle
    evidence: tuple[EvidenceItem, ...]
    brief: ResolutionBrief
    review_reasons: tuple[str, ...]


class TriageWorkflow(Protocol):
    async def run(self, run_id: UUID, submission: IssueSubmission) -> WorkflowResult: ...
    async def resume(self, run_id: UUID, decision: ReviewDecision) -> WorkflowResult: ...


class RunRepository(Protocol):
    async def initialize(self) -> None: ...
    async def recover_interrupted(self) -> int: ...
    async def create_or_get(
        self, submission: IssueSubmission
    ) -> tuple[TriageRunSnapshot, bool]: ...
    async def get(self, run_id: UUID) -> TriageRunSnapshot | None: ...
    async def save(self, snapshot: TriageRunSnapshot) -> None: ...
    async def append_event(
        self, run_id: UUID, kind: EventKind, payload: dict[str, object]
    ) -> RunEvent: ...
    async def save_with_event(
        self, snapshot: TriageRunSnapshot, kind: EventKind, payload: dict[str, object]
    ) -> RunEvent: ...
    async def events_after(self, run_id: UUID, sequence: int) -> tuple[RunEvent, ...]: ...
    async def save_decision(self, run_id: UUID, decision: ReviewDecision) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: RunEvent) -> None: ...
