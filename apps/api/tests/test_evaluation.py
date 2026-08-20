from datetime import UTC, datetime

import pytest

from repomedic.adapters.corpus import GitHubCorpusClient, build_corpus, chunk_source
from repomedic.adapters.github import IssueRecord
from repomedic.domain.models import IssueType
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
