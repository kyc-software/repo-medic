"""Create, execute, and decide use cases."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from repomedic.application.ports import (
    EventPublisher,
    RunRepository,
    TriageWorkflow,
)
from repomedic.domain.models import (
    ApproveDecision,
    AwaitingReviewRun,
    CompletedRun,
    EditDecision,
    EventKind,
    FailedRun,
    IssueSubmission,
    RejectDecision,
    RejectedRun,
    ReviewDecision,
    RunningPhase,
    RunningRun,
    TriageRunSnapshot,
    now_utc,
)
from repomedic.domain.policy import DomainConflictError, validate_citations

LOGGER = logging.getLogger(__name__)


class TrackedRunExecutor:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, execution: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(execution)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


class TriageService:
    def __init__(
        self,
        repository: RunRepository,
        publisher: EventPublisher,
        workflow: TriageWorkflow,
        executor: TrackedRunExecutor,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.workflow = workflow
        self.executor = executor

    async def create_run(self, submission: IssueSubmission) -> TriageRunSnapshot:
        snapshot, created = await self.repository.create_or_get(submission)
        if created:
            await self._event(snapshot.run_id, EventKind.RUN_QUEUED, {"status": "queued"})
            self.executor.start(self.execute_run(snapshot.run_id))
        return snapshot

    async def get_run(self, run_id: UUID) -> TriageRunSnapshot | None:
        return await self.repository.get(run_id)

    async def execute_run(self, run_id: UUID) -> None:
        current = await self.repository.get(run_id)
        if current is None:
            return
        try:
            running = RunningRun(
                run_id=run_id,
                submission=current.submission,
                phase=RunningPhase.PREDICTING,
                created_at=current.created_at,
                updated_at=now_utc(),
            )
            await self._save_phase(running)
            workflow_result = await self.workflow.run(run_id, running.submission)
            running = running.model_copy(
                update={"phase": RunningPhase.INVESTIGATING, "updated_at": now_utc()}
            )
            await self._save_phase(running)
            prediction = workflow_result.prediction
            evidence = workflow_result.evidence
            running = running.model_copy(
                update={"phase": RunningPhase.DRAFTING, "updated_at": now_utc()}
            )
            await self._save_phase(running)
            brief = workflow_result.brief
            reasons = workflow_result.review_reasons
            if reasons:
                awaiting = AwaitingReviewRun(
                    run_id=run_id,
                    submission=running.submission,
                    prediction=prediction,
                    evidence=evidence,
                    draft=brief,
                    review_reasons=reasons,
                    created_at=running.created_at,
                    updated_at=now_utc(),
                )
                await self._persist(
                    awaiting,
                    EventKind.REVIEW_REQUIRED,
                    {"snapshot": awaiting.model_dump(mode="json")},
                )
                return
            completed = CompletedRun(
                run_id=run_id,
                submission=running.submission,
                prediction=prediction,
                evidence=evidence,
                brief=brief,
                created_at=running.created_at,
                updated_at=now_utc(),
            )
            await self._persist(
                completed,
                EventKind.RUN_COMPLETED,
                {"snapshot": completed.model_dump(mode="json")},
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("triage execution failed", extra={"run_id": str(run_id)})
            failed = FailedRun(
                run_id=run_id,
                submission=current.submission,
                error_code="workflow_failed",
                retryable=True,
                created_at=current.created_at,
                updated_at=now_utc(),
            )
            await self._persist(
                failed,
                EventKind.RUN_FAILED,
                {"snapshot": failed.model_dump(mode="json")},
            )

    async def decide(self, run_id: UUID, decision: ReviewDecision) -> TriageRunSnapshot:
        current = await self.repository.get(run_id)
        if current is None:
            raise LookupError(f"run {run_id} does not exist")
        if not isinstance(current, AwaitingReviewRun):
            raise DomainConflictError("run is not awaiting review")
        if isinstance(decision, EditDecision):
            validate_citations(decision.brief, current.evidence)
        await self.workflow.resume(run_id, decision)
        await self.repository.save_decision(run_id, decision)
        if isinstance(decision, RejectDecision):
            result: TriageRunSnapshot = RejectedRun(
                run_id=run_id,
                submission=current.submission,
                reason=decision.reason,
                created_at=current.created_at,
                updated_at=now_utc(),
            )
            event_kind = EventKind.RUN_REJECTED
        else:
            brief = decision.brief if isinstance(decision, EditDecision) else current.draft
            if isinstance(decision, ApproveDecision):
                brief = current.draft
            validate_citations(brief, current.evidence)
            result = CompletedRun(
                run_id=run_id,
                submission=current.submission,
                prediction=current.prediction,
                evidence=current.evidence,
                brief=brief,
                created_at=current.created_at,
                updated_at=now_utc(),
            )
            event_kind = EventKind.RUN_COMPLETED
        await self._persist(
            result,
            event_kind,
            {"snapshot": result.model_dump(mode="json")},
        )
        return result

    async def _save_phase(self, snapshot: RunningRun) -> None:
        await self._persist(
            snapshot,
            EventKind.RUN_PHASE,
            {"phase": snapshot.phase, "snapshot": snapshot.model_dump(mode="json")},
        )

    async def _persist(
        self,
        snapshot: TriageRunSnapshot,
        kind: EventKind,
        payload: dict[str, object],
    ) -> None:
        event = await self.repository.save_with_event(snapshot, kind, payload)
        await self.publisher.publish(event)

    async def _event(self, run_id: UUID, kind: EventKind, payload: dict[str, object]) -> None:
        event = await self.repository.append_event(run_id, kind, payload)
        await self.publisher.publish(event)
