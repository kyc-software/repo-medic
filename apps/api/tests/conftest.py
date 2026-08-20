from collections.abc import Generator

import pytest

from repomedic.config import get_settings


@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "")
    monkeypatch.setenv("REPOMEDIC_MLFLOW_TRACKING_URI", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
