from uuid import UUID

from pydantic import BaseModel, HttpUrl


class RunAccepted(BaseModel):
    run_id: UUID
    snapshot_url: HttpUrl
    events_url: HttpUrl


class DecisionAccepted(BaseModel):
    run_id: UUID
    status: str


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    mode: str
    checks: dict[str, bool]
