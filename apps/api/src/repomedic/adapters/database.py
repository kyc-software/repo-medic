"""SQLite lifecycle, decision, and ordered event owner."""

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from repomedic.application.ports import EventPublisher
from repomedic.domain.models import (
    EventKind,
    FailedRun,
    IssueSubmission,
    QueuedRun,
    ReviewDecision,
    RunEvent,
    TriageRunSnapshot,
    now_utc,
)

SNAPSHOT_ADAPTER: TypeAdapter[TriageRunSnapshot] = TypeAdapter(TriageRunSnapshot)
DECISION_ADAPTER: TypeAdapter[ReviewDecision] = TypeAdapter(ReviewDecision)
EVENT_ADAPTER: TypeAdapter[RunEvent] = TypeAdapter(RunEvent)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "triage_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_request_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)
    decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("triage_runs.run_id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    event_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SqliteRunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def recover_interrupted(self) -> int:
        recovered = 0
        async with self._write_lock, self._sessions() as session:
            rows = (
                await session.scalars(
                    select(RunRow).where(RunRow.status.in_(("queued", "running")))
                )
            ).all()
            for row in rows:
                previous = SNAPSHOT_ADAPTER.validate_json(row.snapshot_json)
                failed = FailedRun(
                    run_id=previous.run_id,
                    submission=previous.submission,
                    error_code="process_restarted",
                    retryable=True,
                    created_at=previous.created_at,
                    updated_at=now_utc(),
                )
                row.status = failed.status
                row.snapshot_json = failed.model_dump_json()
                row.updated_at = failed.updated_at
                last_sequence = await session.scalar(
                    select(func.max(EventRow.sequence)).where(EventRow.run_id == row.run_id)
                )
                event = EVENT_ADAPTER.validate_python(
                    {
                        "sequence": (last_sequence or 0) + 1,
                        "run_id": failed.run_id,
                        "kind": EventKind.RUN_FAILED,
                        "timestamp": failed.updated_at,
                        "payload": {"snapshot": failed.model_dump(mode="json")},
                    }
                )
                session.add(
                    EventRow(
                        run_id=row.run_id,
                        sequence=event.sequence,
                        kind=event.kind,
                        event_json=event.model_dump_json(),
                        created_at=event.timestamp,
                    )
                )
                recovered += 1
            await session.commit()
        return recovered

    async def create_or_get(self, submission: IssueSubmission) -> tuple[TriageRunSnapshot, bool]:
        async with self._write_lock, self._sessions() as session:
            existing = await session.scalar(
                select(RunRow).where(RunRow.client_request_id == submission.client_request_id)
            )
            if existing is not None:
                return SNAPSHOT_ADAPTER.validate_json(existing.snapshot_json), False
            created = now_utc()
            snapshot = QueuedRun(run_id=uuid4(), submission=submission, created_at=created)
            session.add(
                RunRow(
                    run_id=str(snapshot.run_id),
                    client_request_id=submission.client_request_id,
                    status=snapshot.status,
                    snapshot_json=snapshot.model_dump_json(),
                    created_at=created,
                    updated_at=created,
                )
            )
            await session.commit()
            return snapshot, True

    async def get(self, run_id: UUID) -> TriageRunSnapshot | None:
        async with self._sessions() as session:
            row = await session.get(RunRow, str(run_id))
            return None if row is None else SNAPSHOT_ADAPTER.validate_json(row.snapshot_json)

    async def save(self, snapshot: TriageRunSnapshot) -> None:
        async with self._write_lock, self._sessions() as session:
            row = await session.get(RunRow, str(snapshot.run_id))
            if row is None:
                raise LookupError(f"run {snapshot.run_id} does not exist")
            row.status = snapshot.status
            row.snapshot_json = snapshot.model_dump_json()
            row.updated_at = getattr(snapshot, "updated_at", snapshot.created_at)
            await session.commit()

    async def append_event(
        self, run_id: UUID, kind: EventKind, payload: dict[str, object]
    ) -> RunEvent:
        async with self._write_lock, self._sessions() as session:
            last_sequence = await session.scalar(
                select(func.max(EventRow.sequence)).where(EventRow.run_id == str(run_id))
            )
            event = EVENT_ADAPTER.validate_python(
                {
                    "sequence": (last_sequence or 0) + 1,
                    "run_id": run_id,
                    "kind": kind,
                    "timestamp": now_utc(),
                    "payload": payload,
                }
            )
            session.add(
                EventRow(
                    run_id=str(run_id),
                    sequence=event.sequence,
                    kind=event.kind,
                    event_json=event.model_dump_json(),
                    created_at=event.timestamp,
                )
            )
            await session.commit()
            return event

    async def save_with_event(
        self, snapshot: TriageRunSnapshot, kind: EventKind, payload: dict[str, object]
    ) -> RunEvent:
        async with self._write_lock, self._sessions() as session:
            row = await session.get(RunRow, str(snapshot.run_id))
            if row is None:
                raise LookupError(f"run {snapshot.run_id} does not exist")
            last_sequence = await session.scalar(
                select(func.max(EventRow.sequence)).where(EventRow.run_id == str(snapshot.run_id))
            )
            event = EVENT_ADAPTER.validate_python(
                {
                    "sequence": (last_sequence or 0) + 1,
                    "run_id": snapshot.run_id,
                    "kind": kind,
                    "timestamp": now_utc(),
                    "payload": payload,
                }
            )
            row.status = snapshot.status
            row.snapshot_json = snapshot.model_dump_json()
            row.updated_at = getattr(snapshot, "updated_at", snapshot.created_at)
            session.add(
                EventRow(
                    run_id=str(snapshot.run_id),
                    sequence=event.sequence,
                    kind=event.kind,
                    event_json=event.model_dump_json(),
                    created_at=event.timestamp,
                )
            )
            await session.commit()
            return event

    async def events_after(self, run_id: UUID, sequence: int) -> tuple[RunEvent, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(EventRow)
                    .where(EventRow.run_id == str(run_id), EventRow.sequence > sequence)
                    .order_by(EventRow.sequence)
                )
            ).all()
            return tuple(EVENT_ADAPTER.validate_json(row.event_json) for row in rows)

    async def save_decision(self, run_id: UUID, decision: ReviewDecision) -> None:
        async with self._write_lock, self._sessions() as session:
            row = await session.get(RunRow, str(run_id))
            if row is None:
                raise LookupError(f"run {run_id} does not exist")
            row.decision_json = DECISION_ADAPTER.dump_json(decision).decode()
            row.updated_at = now_utc()
            await session.commit()


def create_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        raw_path = database_url.rsplit("///", maxsplit=1)[-1]
        if raw_path != ":memory:":
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(database_url)


class InProcessEventBroker(EventPublisher):
    def __init__(self) -> None:
        self._events: dict[UUID, asyncio.Event] = {}

    async def publish(self, event: RunEvent) -> None:
        self._events.setdefault(event.run_id, asyncio.Event()).set()

    async def wait(self, run_id: UUID, wait_seconds: float = 15.0) -> None:
        event = self._events.setdefault(run_id, asyncio.Event())
        try:
            async with asyncio.timeout(wait_seconds):
                await event.wait()
        except TimeoutError:
            return
        finally:
            event.clear()
