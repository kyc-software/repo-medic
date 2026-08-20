"""FastAPI boundary. OpenAPI here is authoritative for browser contracts."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID

import mlflow
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from openai import AsyncOpenAI
from pydantic import HttpUrl
from sse_starlette import EventSourceResponse, ServerSentEvent

from repomedic.adapters.database import InProcessEventBroker, SqliteRunRepository, create_engine
from repomedic.adapters.demo import (
    DemoInvestigator,
    DemoPredictor,
    DemoResolutionWriter,
    DemoRetriever,
)
from repomedic.adapters.openai_agents import OpenAIInvestigator, OpenAIResolutionWriter
from repomedic.adapters.predictive_models import SklearnPredictor
from repomedic.adapters.retrieval import ChromaRetriever, EmbeddingCache, OpenAIEmbeddingClient
from repomedic.application.ports import Investigator, Predictor, ResolutionWriter, Retriever
from repomedic.application.service import TrackedRunExecutor, TriageService
from repomedic.config import Settings, get_settings
from repomedic.domain.models import IssueSubmission, ReviewDecision, RunEvent, TriageRunSnapshot
from repomedic.domain.policy import DomainConflictError, InvalidCitationError
from repomedic.transport.schemas import (
    DecisionAccepted,
    HealthResponse,
    ReadyResponse,
    RunAccepted,
)
from repomedic.workflows.triage import LangGraphTriageWorkflow

TERMINAL_STATES = {"completed", "rejected", "failed"}


def build_service(
    settings: Settings,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> tuple[TriageService, SqliteRunRepository, InProcessEventBroker]:
    repository = SqliteRunRepository(create_engine(settings.database_url))
    broker = InProcessEventBroker()
    predictor: Predictor
    retriever: Retriever
    investigator: Investigator
    writer: ResolutionWriter
    if settings.mode == "live":
        if settings.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY is required in live mode")
        embeddings = OpenAIEmbeddingClient(
            settings.openai_api_key,
            settings.embedding_model,
            EmbeddingCache(settings.chroma_path / "embedding-cache.sqlite"),
        )
        retriever = ChromaRetriever(settings.chroma_path, embeddings)
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        predictor = SklearnPredictor(settings.model_path / "models.joblib")
        investigator = OpenAIInvestigator(openai_client, settings.llm_model, retriever)
        writer = OpenAIResolutionWriter(openai_client, settings.llm_model)
    else:
        predictor = DemoPredictor()
        retriever = DemoRetriever()
        investigator = DemoInvestigator()
        writer = DemoResolutionWriter()
    workflow = LangGraphTriageWorkflow(
        predictor=predictor,
        retriever=retriever,
        investigator=investigator,
        writer=writer,
        checkpointer=checkpointer,
        trace_enabled=bool(settings.mlflow_tracking_uri),
    )
    service = TriageService(
        repository=repository,
        publisher=broker,
        workflow=workflow,
        executor=TrackedRunExecutor(),
    )
    return service, repository, broker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ensure_data_directories(settings)
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
        await saver.setup()
        service, repository, broker = build_service(settings, saver)
        await _start_application(app, settings, service, repository, broker)
        yield
        await service.executor.close()


async def _start_application(
    app: FastAPI,
    settings: Settings,
    service: TriageService,
    repository: SqliteRunRepository,
    broker: InProcessEventBroker,
) -> None:
    if settings.mlflow_tracking_uri:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.openai.autolog(log_traces=True, silent=True)
    await repository.initialize()
    await repository.recover_interrupted()
    app.state.settings = settings
    app.state.service = service
    app.state.repository = repository
    app.state.broker = broker


app = FastAPI(
    title="RepoMedic API",
    version="0.1.0",
    description="Evidence-backed issue triage for scikit-learn/scikit-learn",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)


def get_service(request: Request) -> TriageService:
    return cast(TriageService, request.app.state.service)


def get_repository(request: Request) -> SqliteRunRepository:
    return cast(SqliteRunRepository, request.app.state.repository)


def get_broker(request: Request) -> InProcessEventBroker:
    return cast(InProcessEventBroker, request.app.state.broker)


@app.get("/api/v1/health", response_model=HealthResponse, tags=["operations"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/v1/ready", response_model=ReadyResponse, tags=["operations"])
async def ready(request: Request) -> ReadyResponse:
    settings: Settings = request.app.state.settings
    database_ok = await request.app.state.repository.get(UUID(int=0)) is None
    checks = {
        "database": database_ok,
        "models": settings.mode == "demo" or (settings.model_path / "models.joblib").exists(),
        "chroma": settings.mode == "demo" or (settings.chroma_path / "corpus.ready").exists(),
        "openai": settings.mode == "demo" or bool(settings.openai_api_key),
        "checkpoint_store": settings.mode == "demo" or settings.checkpoint_path.exists(),
    }
    response_status = "ready" if all(checks.values()) else "not_ready"
    if response_status != "ready":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=checks)
    return ReadyResponse(status=response_status, mode=settings.mode, checks=checks)


@app.post(
    "/api/v1/triage-runs",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["triage"],
)
async def create_run(
    submission: IssueSubmission,
    request: Request,
    service: Annotated[TriageService, Depends(get_service)],
) -> RunAccepted:
    snapshot = await service.create_run(submission)
    base = str(request.base_url).rstrip("/")
    return RunAccepted(
        run_id=snapshot.run_id,
        snapshot_url=HttpUrl(f"{base}/api/v1/triage-runs/{snapshot.run_id}"),
        events_url=HttpUrl(f"{base}/api/v1/triage-runs/{snapshot.run_id}/events"),
    )


@app.get(
    "/api/v1/triage-runs/{run_id}",
    response_model=TriageRunSnapshot,
    tags=["triage"],
)
async def get_run(
    run_id: UUID, service: Annotated[TriageService, Depends(get_service)]
) -> TriageRunSnapshot:
    snapshot = await service.get_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return snapshot


@app.post(
    "/api/v1/triage-runs/{run_id}/decision",
    response_model=DecisionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["triage"],
)
async def decide_run(
    run_id: UUID,
    decision: ReviewDecision,
    service: Annotated[TriageService, Depends(get_service)],
) -> DecisionAccepted:
    try:
        result = await service.decide(run_id, decision)
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        ) from error
    except (DomainConflictError, InvalidCitationError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return DecisionAccepted(run_id=run_id, status=result.status)


@app.get(
    "/api/v1/triage-runs/{run_id}/events",
    tags=["triage"],
    responses={
        200: {
            "model": RunEvent,
            "description": "Server-sent RunEvent frames with ordered replay IDs",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_events(
    run_id: UUID,
    request: Request,
    repository: Annotated[SqliteRunRepository, Depends(get_repository)],
    broker: Annotated[InProcessEventBroker, Depends(get_broker)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> Response:
    if await repository.get(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    try:
        starting_sequence = int(last_event_id or "0")
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Last-Event-ID"
        ) from error

    async def event_stream() -> AsyncIterator[ServerSentEvent]:
        sequence = starting_sequence
        while not await request.is_disconnected():
            events = await repository.events_after(run_id, sequence)
            for event in events:
                sequence = event.sequence
                yield ServerSentEvent(
                    data=event.model_dump_json(),
                    event=event.kind,
                    id=str(event.sequence),
                )
            snapshot = await repository.get(run_id)
            if snapshot is not None and snapshot.status in TERMINAL_STATES:
                return
            try:
                await asyncio.wait_for(broker.wait(run_id), timeout=15)
            except TimeoutError:
                yield ServerSentEvent(comment="heartbeat")

    return EventSourceResponse(event_stream())


def ensure_data_directories(settings: Settings) -> None:
    for path in (settings.checkpoint_path.parent, settings.chroma_path, settings.model_path):
        Path(path).mkdir(parents=True, exist_ok=True)
