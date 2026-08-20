import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import HttpUrl

from repomedic.adapters.corpus import GitHubCorpusClient, build_corpus, chunk_source, chunk_text
from repomedic.adapters.github import IssueRecord
from repomedic.adapters.retrieval import (
    ChromaRetriever,
    CorpusChunk,
    EmbeddingCache,
    OpenAIEmbeddingClient,
)
from repomedic.domain.models import IssueType, SourceKind
from repomedic.evaluation.retrieval import RetrievalCase, retrieval_metrics


def test_retrieval_metrics_measure_hit_at_three_and_reciprocal_rank() -> None:
    cases = (
        RetrievalCase(case_id="one", query="q1", relevant_source_ids=("a",)),
        RetrievalCase(case_id="two", query="q2", relevant_source_ids=("b",)),
    )
    metrics = retrieval_metrics(cases, {"one": ("x", "a#function"), "two": ("x", "y", "z")})
    assert metrics == {"hit_at_3": 0.5, "mrr": 0.25}


def test_python_corpus_chunks_at_symbol_boundaries() -> None:
    chunks = tuple(
        chunk_source(
            "module.py",
            "CONSTANT = 1\n\ndef first():\n    return 1\n\nclass Second:\n    pass\n",
        )
    )
    assert chunks == ("def first():\n    return 1", "class Second:\n    pass")


def test_corpus_chunks_never_exceed_target_size() -> None:
    content = "x" * 6_001

    assert max(map(len, chunk_text(content, 2_400))) <= 2_400
    python_chunks = chunk_source("module.py", f"def large():\n    value = '{content}'")
    assert max(map(len, python_chunks)) <= 2_400


@pytest.mark.asyncio
async def test_zero_resolved_limit_does_not_fetch_issue_comments() -> None:
    class StubCorpusClient(GitHubCorpusClient):
        def __init__(self) -> None:
            self.repository = "owner/repository"

        async def repository_sha(self) -> str:
            return "abcdef0"

        async def source(self, path: str, sha: str) -> str | None:
            return None

        async def final_maintainer_comment(self, issue_number: int) -> str | None:
            raise AssertionError("comment fetch must not run")

    issue = IssueRecord(
        number=1,
        title="Closed issue",
        body="Resolved body",
        url="https://github.com/owner/repository/issues/1",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        closed_at=datetime(2024, 1, 2, tzinfo=UTC),
        issue_type=IssueType.BUG,
    )
    assert await build_corpus(StubCorpusClient(), (issue,), resolved_limit=0) == ()


@pytest.mark.asyncio
async def test_embedding_client_reads_cached_vector(tmp_path: Path) -> None:
    text = "cached repository evidence"
    model = "test-embedding-model"
    cache = EmbeddingCache(tmp_path / "embeddings.sqlite")
    cache.put(hashlib.sha256(text.encode()).hexdigest(), model, [0.1, 0.2])

    client = OpenAIEmbeddingClient("unused", model, cache)

    assert await client.embed(text) == [0.1, 0.2]


@pytest.mark.asyncio
async def test_reindex_removes_stale_chunks(tmp_path: Path) -> None:
    class FixedEmbeddings:
        async def embed(self, text: str) -> list[float]:
            return [float(len(text)), 1.0]

    path = tmp_path / "chroma"
    retriever = ChromaRetriever(path, FixedEmbeddings())

    def chunk(source_id: str) -> CorpusChunk:
        return CorpusChunk(
            source_id=source_id,
            source_kind=SourceKind.CODE,
            url=HttpUrl("https://github.com/owner/repository"),
            repository_sha="abcdef0",
            text=source_id,
        )

    await retriever.index((chunk("old"),))
    await retriever.index((chunk("new"),))

    assert set(retriever.source_ids()) == {"new"}
