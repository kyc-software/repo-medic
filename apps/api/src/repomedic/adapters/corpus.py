"""Curated repository docs/code plus resolved-issue maintainer context."""

import ast
import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
from pydantic import HttpUrl

from repomedic.adapters.github import IssueRecord
from repomedic.adapters.retrieval import CorpusChunk
from repomedic.domain.models import SourceKind

CURATED_FILES: tuple[tuple[str, str, SourceKind], ...] = (
    ("docs-common-pitfalls", "doc/common_pitfalls.rst", SourceKind.DOCUMENTATION),
    ("docs-pipeline", "doc/modules/compose.rst", SourceKind.DOCUMENTATION),
    ("docs-cross-validation", "doc/modules/cross_validation.rst", SourceKind.DOCUMENTATION),
    ("docs-model-evaluation", "doc/modules/model_evaluation.rst", SourceKind.DOCUMENTATION),
    ("docs-calibration", "doc/modules/calibration.rst", SourceKind.DOCUMENTATION),
    ("docs-developers", "doc/developers/develop.rst", SourceKind.DOCUMENTATION),
    ("docs-model-persistence", "doc/model_persistence.rst", SourceKind.DOCUMENTATION),
    ("docs-computing", "doc/computing/parallelism.rst", SourceKind.DOCUMENTATION),
    ("docs-contributing", "CONTRIBUTING.md", SourceKind.DOCUMENTATION),
    ("code-validation", "sklearn/utils/validation.py", SourceKind.CODE),
    ("code-base-estimator", "sklearn/base.py", SourceKind.CODE),
    ("code-split", "sklearn/model_selection/_split.py", SourceKind.CODE),
)


class GitHubCorpusClient:
    def __init__(self, repository: str, token: str | None = None) -> None:
        self.repository = repository
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com", headers=headers, timeout=30
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def repository_sha(self) -> str:
        repository = await self._get(f"/repos/{self.repository}")
        repository.raise_for_status()
        branch = repository.json()["default_branch"]
        commit = await self._get(f"/repos/{self.repository}/commits/{branch}")
        commit.raise_for_status()
        return str(commit.json()["sha"])

    async def source(self, path: str, sha: str) -> str | None:
        response = await self._get(
            f"/repos/{self.repository}/contents/{path}",
            params={"ref": sha},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text

    async def final_maintainer_comment(self, issue_number: int) -> str | None:
        response = await self._get(
            f"/repos/{self.repository}/issues/{issue_number}/comments",
            params={"per_page": 100},
        )
        response.raise_for_status()
        comments = response.json()
        for comment in reversed(comments):
            if comment.get("author_association") in {"MEMBER", "OWNER", "COLLABORATOR"}:
                body = comment.get("body")
                return str(body) if body else None
        return None

    async def _get(
        self,
        url: str,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        while True:
            response = await self._client.get(url, params=params, headers=headers)
            if response.status_code != 403 or response.headers.get("x-ratelimit-remaining") != "0":
                return response
            reset = int(response.headers.get("x-ratelimit-reset", "0"))
            delay = max(reset - int(datetime.now(UTC).timestamp()), 1)
            await asyncio.sleep(delay)


async def build_corpus(
    client: GitHubCorpusClient,
    issues: tuple[IssueRecord, ...],
    resolved_limit: int = 50,
) -> tuple[CorpusChunk, ...]:
    sha = await client.repository_sha()
    source_results = await asyncio.gather(
        *(client.source(path, sha) for _, path, _ in CURATED_FILES)
    )
    chunks: list[CorpusChunk] = []
    for (source_id, path, source_kind), content in zip(CURATED_FILES, source_results, strict=True):
        if content is None:
            continue
        url = HttpUrl(f"https://github.com/{client.repository}/blob/{sha}/{path}")
        for index, text in enumerate(chunk_source(path, content)):
            chunks.append(
                CorpusChunk(
                    source_id=f"{source_id}#{index}",
                    source_kind=source_kind,
                    url=url,
                    repository_sha=sha,
                    path=path,
                    text=text,
                )
            )

    closed_issues = [issue for issue in issues if issue.closed_at is not None]
    resolved = closed_issues[-resolved_limit:] if resolved_limit else []
    comments = await asyncio.gather(
        *(client.final_maintainer_comment(issue.number) for issue in resolved)
    )
    for issue, comment in zip(resolved, comments, strict=True):
        context = f"{issue.title}\n\n{issue.body}"
        if comment:
            context += f"\n\nFinal maintainer context:\n{comment}"
        for index, text in enumerate(chunk_text(context, 2_400)):
            chunks.append(
                CorpusChunk(
                    source_id=f"issue-{issue.number}#{index}",
                    source_kind=SourceKind.RESOLVED_ISSUE,
                    url=HttpUrl(issue.url),
                    repository_sha=sha,
                    issue_number=issue.number,
                    text=text,
                )
            )
    return tuple(chunks)


def chunk_source(path: str, content: str, target_chars: int = 2_400) -> Iterable[str]:
    if path.endswith(".py"):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return chunk_text(content, target_chars)
        chunks = [
            ast.get_source_segment(content, node) or ""
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        return tuple(part for chunk in chunks if chunk for part in chunk_text(chunk, target_chars))
    return chunk_text(content, target_chars)


def chunk_text(content: str, target_chars: int) -> tuple[str, ...]:
    if target_chars < 1:
        raise ValueError("target_chars must be positive")
    paragraphs = (
        piece
        for paragraph in content.split("\n\n")
        for piece in (
            paragraph[index : index + target_chars]
            for index in range(0, max(len(paragraph), 1), target_chars)
        )
    )
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        separator_size = 2 if current else 0
        if current and current_size + separator_size + len(paragraph) > target_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(paragraph)
        current_size += (2 if len(current) > 1 else 0) + len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return tuple(chunks)
