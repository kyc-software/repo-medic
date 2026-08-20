import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from repomedic.adapters.database import InProcessEventBroker, SqliteRunRepository, create_engine
from repomedic.adapters.demo import (
    DemoInvestigator,
    DemoPredictor,
    DemoResolutionWriter,
    DemoRetriever,
)
from repomedic.application.service import TrackedRunExecutor, TriageService
from repomedic.domain.models import (
    ApproveDecision,
    AwaitingReviewRun,
    CompletedRun,
    EventKind,
    FailedRun,
    IssueSubmission,
    RejectDecision,
    RejectedRun,
    RunFailedEvent,
)
from repomedic.domain.policy import DomainConflictError
from repomedic.workflows.triage import LangGraphTriageWorkflow


@pytest_asyncio.fixture
async def service(
    tmp_path: Path,
) -> AsyncIterator[tuple[TriageService, SqliteRunRepository, AsyncEngine]]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    repository = SqliteRunRepository(engine)
    await repository.initialize()
    workflow = LangGraphTriageWorkflow(
        predictor=DemoPredictor(),
        retriever=DemoRetriever(),
        investigator=DemoInvestigator(),
        writer=DemoResolutionWriter(),
    )
    triage_service = TriageService(
        repository=repository,
        publisher=InProcessEventBroker(),
        workflow=workflow,
        executor=TrackedRunExecutor(),
    )
    yield triage_service, repository, engine
    await triage_service.executor.close()
    await engine.dispose()


async def wait_for_terminal(service: TriageService, run_id: UUID) -> object:
    for _ in range(100):
        snapshot = await service.get_run(run_id)
        if snapshot is not None and snapshot.status in {
            "completed",
            "awaiting_review",
            "rejected",
            "failed",
        }:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError("run did not reach a decision state")


@pytest.mark.asyncio
async def test_clear_issue_completes_with_predictions_and_citations(
    service: tuple[TriageService, SqliteRunRepository, AsyncEngine],
) -> None:
    triage, repository, _ = service
    submission = IssueSubmission(
        client_request_id="clear-request-001",
        title="Pipeline raises unexpected validation error",
        body="A minimal pipeline raises after fitting when input dtype changes.",
    )
    accepted = await triage.create_run(submission)
    result = await wait_for_terminal(triage, accepted.run_id)

    assert isinstance(result, CompletedRun)
    assert result.prediction.classifier_version
    assert set(result.brief.citation_ids) <= {item.source_id for item in result.evidence}
    events = await repository.events_after(accepted.run_id, 0)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].kind == "run.completed"


@pytest.mark.asyncio
async def test_duplicate_submission_returns_same_run_and_single_event_stream(
    service: tuple[TriageService, SqliteRunRepository, AsyncEngine],
) -> None:
    triage, repository, _ = service
    submission = IssueSubmission(
        client_request_id="duplicate-request-001",
        title="Question about estimator behavior",
        body="How should this estimator handle a sparse matrix after transform?",
    )
    first = await triage.create_run(submission)
    second = await triage.create_run(submission)
    await wait_for_terminal(triage, first.run_id)

    assert first.run_id == second.run_id
    events = await repository.events_after(first.run_id, 0)
    assert sum(event.kind == "run.queued" for event in events) == 1


@pytest.mark.asyncio
async def test_ambiguous_issue_can_be_approved_then_rejects_late_decision(
    service: tuple[TriageService, SqliteRunRepository, AsyncEngine],
) -> None:
    triage, _, _ = service
    submission = IssueSubmission(
        client_request_id="ambiguous-request-001",
        title="Classifier maybe fails sometimes",
        body="This is unclear and sometimes changes depending on unknown input.",
    )
    accepted = await triage.create_run(submission)
    awaiting = await wait_for_terminal(triage, accepted.run_id)
    assert isinstance(awaiting, AwaitingReviewRun)

    completed = await triage.decide(accepted.run_id, ApproveDecision())
    assert isinstance(completed, CompletedRun)
    with pytest.raises(DomainConflictError):
        await triage.decide(accepted.run_id, RejectDecision(reason="duplicate decision"))


@pytest.mark.asyncio
async def test_ambiguous_issue_can_be_rejected(
    service: tuple[TriageService, SqliteRunRepository, AsyncEngine],
) -> None:
    triage, _, _ = service
    accepted = await triage.create_run(
        IssueSubmission(
            client_request_id="ambiguous-request-002",
            title="Maybe a feature or bug",
            body="Unclear request with maybe several incompatible outcomes.",
        )
    )
    await wait_for_terminal(triage, accepted.run_id)
    result = await triage.decide(accepted.run_id, RejectDecision(reason="Needs reproduction"))
    assert isinstance(result, RejectedRun)


@pytest.mark.asyncio
async def test_restart_recovery_persists_matching_terminal_event(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}")
    repository = SqliteRunRepository(engine)
    await repository.initialize()
    snapshot, _ = await repository.create_or_get(
        IssueSubmission(
            client_request_id="restart-request-001",
            title="Run interrupted during process restart",
            body="Queued work must become a retryable terminal failure with an event.",
        )
    )
    await repository.append_event(snapshot.run_id, EventKind.RUN_QUEUED, {"status": "queued"})

    assert await repository.recover_interrupted() == 1
    recovered = await repository.get(snapshot.run_id)
    events = await repository.events_after(snapshot.run_id, 0)
    assert isinstance(recovered, FailedRun)
    assert isinstance(events[-1], RunFailedEvent)
    assert events[-1].payload.snapshot == recovered
    await engine.dispose()
