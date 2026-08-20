import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repomedic.config import get_settings
from repomedic.transport.app import app


def test_api_create_snapshot_and_decision_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMEDIC_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("REPOMEDIC_CHECKPOINT_PATH", str(tmp_path / "checkpoints.db"))
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        response = client.post(
            "/api/v1/triage-runs",
            json={
                "client_request_id": "api-request-0001",
                "title": "Validation failure after transform",
                "body": "Pipeline fails with a stable traceback after dtype conversion.",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/v1/triage-runs/{run_id}")
            if snapshot.json()["status"] == "completed":
                break
            time.sleep(0.01)
        assert snapshot.status_code == 200
        assert snapshot.json()["status"] == "completed"
        conflict = client.post(f"/api/v1/triage-runs/{run_id}/decision", json={"kind": "approve"})
        assert conflict.status_code == 409


def test_awaiting_review_resumes_after_application_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMEDIC_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'review.db'}")
    monkeypatch.setenv("REPOMEDIC_CHECKPOINT_PATH", str(tmp_path / "review-checkpoints.db"))
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/triage-runs",
            json={
                "client_request_id": "restart-review-0001",
                "title": "Classifier maybe fails sometimes",
                "body": "This is unclear and maybe depends on unknown input values.",
            },
        )
        run_id = response.json()["run_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/v1/triage-runs/{run_id}").json()
            if snapshot["status"] == "awaiting_review":
                break
            time.sleep(0.01)
        assert snapshot["status"] == "awaiting_review"

    get_settings.cache_clear()
    with TestClient(app) as restarted:
        decision = restarted.post(
            f"/api/v1/triage-runs/{run_id}/decision", json={"kind": "approve"}
        )
        assert decision.status_code == 202
        snapshot = restarted.get(f"/api/v1/triage-runs/{run_id}").json()
        assert snapshot["status"] == "completed"
