"""GitHub REST boundary with pagination, ETag caching, and rate-limit handling."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field

from repomedic.domain.models import IssueType


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: int
    title: str
    body: str | None = None
    html_url: str
    state: str
    created_at: datetime
    closed_at: datetime | None = None
    labels: list[dict[str, object]] = Field(default_factory=list)
    pull_request: dict[str, object] | None = None


class IssueRecord(BaseModel):
    number: int
    title: str
    body: str
    url: str
    created_at: datetime
    closed_at: datetime | None
    issue_type: IssueType

    @property
    def close_days(self) -> float | None:
        if self.closed_at is None:
            return None
        return max((self.closed_at - self.created_at).total_seconds() / 86_400, 0)


LABEL_RULES: tuple[tuple[IssueType, tuple[str, ...]], ...] = (
    (IssueType.BUG, ("bug", "defect", "regression")),
    (IssueType.DOCUMENTATION, ("documentation", "docs")),
    (IssueType.FEATURE, ("feature", "enhancement", "new feature")),
    (IssueType.QUESTION, ("question", "help")),
)


def map_issue_type(labels: list[dict[str, object]]) -> IssueType:
    names = {
        str(label.get("name", "")).casefold()
        for label in labels
        if isinstance(label.get("name"), str)
    }
    for issue_type, candidates in LABEL_RULES:
        if names.intersection(candidates):
            return issue_type
    return IssueType.QUESTION


class GitHubIssueClient:
    def __init__(
        self,
        repository: str,
        token: str | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self.repository = repository
        self._cache_path = cache_path
        self._cache: dict[str, dict[str, object]] = {}
        if cache_path is not None and cache_path.exists():
            raw_cache = json.loads(cache_path.read_text())
            if isinstance(raw_cache, dict):
                self._cache = raw_cache
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=30,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, limit: int = 5_000) -> tuple[IssueRecord, ...]:
        records: dict[int, IssueRecord] = {}
        page = 1
        while len(records) < limit:
            cache_key = f"issues:all:{page}"
            cached = self._cache.get(cache_key, {})
            etag = cached.get("etag")
            response = await self._client.get(
                f"/repos/{self.repository}/issues",
                params={"state": "all", "per_page": 100, "page": page, "sort": "created"},
                headers={"If-None-Match": str(etag)} if etag else None,
            )
            if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                reset = int(response.headers.get("x-ratelimit-reset", "0"))
                delay = max(reset - int(datetime.now(UTC).timestamp()), 1)
                await asyncio.sleep(delay)
                continue
            if response.status_code == 304:
                raw_payload = cached.get("body", [])
            else:
                response.raise_for_status()
                raw_payload = response.json()
                self._cache[cache_key] = {
                    "etag": response.headers.get("etag", ""),
                    "body": raw_payload,
                }
                self._write_cache()
            if not isinstance(raw_payload, list):
                raise ValueError("GitHub issues response must be a list")
            payload = [GitHubIssue.model_validate(item) for item in raw_payload]
            if not payload:
                break
            for issue in payload:
                if issue.pull_request is not None:
                    continue
                records[issue.number] = IssueRecord(
                    number=issue.number,
                    title=issue.title,
                    body=issue.body or "",
                    url=issue.html_url,
                    created_at=issue.created_at,
                    closed_at=issue.closed_at,
                    issue_type=map_issue_type(issue.labels),
                )
                if len(records) >= limit:
                    break
            page += 1
        return tuple(sorted(records.values(), key=lambda record: record.created_at))

    def _write_cache(self) -> None:
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(self._cache, sort_keys=True))


def write_jsonl(path: Path, records: tuple[IssueRecord, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(record.model_dump_json() for record in records) + "\n")


def read_jsonl(path: Path) -> tuple[IssueRecord, ...]:
    if not path.exists():
        raise FileNotFoundError(f"corpus not found: {path}")
    return tuple(
        IssueRecord.model_validate_json(line) for line in path.read_text().splitlines() if line
    )
