from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REPOMEDIC_", env_file=".env", extra="ignore")

    mode: Literal["demo", "live"] = "demo"
    database_url: str = "sqlite+aiosqlite:///./data/repomedic.db"
    checkpoint_path: Path = Path("./data/checkpoints.sqlite")
    chroma_path: Path = Path("./data/chroma")
    model_path: Path = Path("./data/models")
    github_cache_path: Path = Path("./data/cache/github-pages.json")
    repository: str = "scikit-learn/scikit-learn"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "REPOMEDIC_OPENAI_API_KEY"),
    )
    github_token: str | None = Field(
        default=None, validation_alias=AliasChoices("GITHUB_TOKEN", "REPOMEDIC_GITHUB_TOKEN")
    )
    mlflow_tracking_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MLFLOW_TRACKING_URI", "REPOMEDIC_MLFLOW_TRACKING_URI"),
    )
    llm_model: str = "gpt-5.4-mini"
    embedding_model: str = "text-embedding-3-small"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)


@lru_cache
def get_settings() -> Settings:
    return Settings()
