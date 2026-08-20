"""RepoMedic data and model commands."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mlflow
import typer
from pydantic import HttpUrl, TypeAdapter

from repomedic.adapters.corpus import GitHubCorpusClient, build_corpus
from repomedic.adapters.github import GitHubIssueClient, IssueRecord, read_jsonl, write_jsonl
from repomedic.adapters.predictive_models import evaluate_models, train_models
from repomedic.adapters.retrieval import (
    ChromaRetriever,
    CorpusChunk,
    EmbeddingCache,
    OpenAIEmbeddingClient,
    read_chunks,
    write_chunks,
)
from repomedic.config import get_settings
from repomedic.domain.models import IssueType, SourceKind
from repomedic.evaluation.retrieval import RetrievalCase, retrieval_metrics

RETRIEVAL_CASES_ADAPTER: TypeAdapter[list[RetrievalCase]] = TypeAdapter(list[RetrievalCase])

app = typer.Typer(no_args_is_help=True, help="RepoMedic ETL, training, and corpus tools.")


@app.command()
def ingest(
    output: Path = Path("data/corpus/issues.jsonl"),
    limit: int = typer.Option(5_000, min=1, max=10_000),
) -> None:
    """Fetch reproducible public issue records from configured GitHub repository."""

    async def run() -> tuple[IssueRecord, ...]:
        settings = get_settings()
        client = GitHubIssueClient(
            settings.repository, settings.github_token, settings.github_cache_path
        )
        try:
            return await client.fetch(limit=limit)
        finally:
            await client.close()

    records = asyncio.run(run())
    write_jsonl(output, records)
    typer.echo(f"wrote {len(records)} issues to {output}")


@app.command()
def train(
    corpus: Path = Path("data/corpus/issues.jsonl"),
    artifact: Path = Path("data/models/models.joblib"),
    tracking_uri: str = "sqlite:///data/mlflow.db",
) -> None:
    """Train chronological classifier and close-time regression artifacts."""
    metrics = train_models(read_jsonl(corpus), artifact, tracking_uri)
    typer.echo(json.dumps(metrics, indent=2, sort_keys=True))


@app.command()
def evaluate(
    corpus: Path = Path("data/corpus/issues.jsonl"),
    artifact: Path = Path("data/models/models.joblib"),
) -> None:
    """Evaluate locked artifacts on the untouched chronological test period."""
    metrics = evaluate_models(read_jsonl(corpus), artifact)
    typer.echo(json.dumps(metrics, indent=2, sort_keys=True))


@app.command("build-corpus")
def build_repository_corpus(
    issues: Path = Path("data/corpus/issues.jsonl"),
    output: Path = Path("data/corpus/chunks.jsonl"),
    resolved_limit: int = typer.Option(50, min=0, max=200),
) -> None:
    """Fetch curated docs/code and resolved-issue maintainer context."""
    settings = get_settings()

    async def run() -> tuple[CorpusChunk, ...]:
        client = GitHubCorpusClient(settings.repository, settings.github_token)
        try:
            return await build_corpus(client, read_jsonl(issues), resolved_limit)
        finally:
            await client.close()

    chunks = asyncio.run(run())
    write_chunks(output, chunks)
    typer.echo(f"wrote {len(chunks)} versioned chunks to {output}")


@app.command("index")
def index_corpus(chunks: Path = Path("data/corpus/chunks.jsonl")) -> None:
    """Embed corpus once by content hash and upsert it into local Chroma."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is required to build embeddings")
    cache = EmbeddingCache(settings.chroma_path / "embedding-cache.sqlite")
    embeddings = OpenAIEmbeddingClient(settings.openai_api_key, settings.embedding_model, cache)
    retriever = ChromaRetriever(settings.chroma_path, embeddings)
    count = asyncio.run(retriever.index(read_chunks(chunks)))
    (settings.chroma_path / "corpus.ready").write_text(f"{count}\n")
    typer.echo(f"indexed {count} chunks")


@app.command("evaluate-retrieval")
def evaluate_retrieval(
    golden: Path = Path("apps/api/evaluation/golden-retrieval.json"),
    tracking_uri: str = "sqlite:///data/mlflow.db",
) -> None:
    """Measure Hit@3 and MRR against committed golden cases."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is required for retrieval evaluation")
    cases = RETRIEVAL_CASES_ADAPTER.validate_json(golden.read_text())
    cache = EmbeddingCache(settings.chroma_path / "embedding-cache.sqlite")
    embeddings = OpenAIEmbeddingClient(settings.openai_api_key, settings.embedding_model, cache)
    retriever = ChromaRetriever(settings.chroma_path, embeddings)

    async def run() -> dict[str, tuple[str, ...]]:
        rankings: dict[str, tuple[str, ...]] = {}
        for case in cases:
            evidence = await retriever.retrieve_text(case.query, limit=5)
            rankings[case.case_id] = tuple(item.source_id for item in evidence)
        return rankings

    metrics = retrieval_metrics(cases, asyncio.run(run()))
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("repomedic-retrieval")
    with mlflow.start_run():
        mlflow.log_metrics(metrics)
        mlflow.log_param("golden_cases", len(cases))
    typer.echo(json.dumps(metrics, indent=2, sort_keys=True))


@app.command("seed-demo")
def seed_demo(output_dir: Path = Path("data/corpus")) -> None:
    """Create deterministic offline fixtures for rehearsal and tests."""
    created = datetime(2024, 1, 1, tzinfo=UTC)
    types = tuple(IssueType)
    records = tuple(
        IssueRecord(
            number=30_000 + index,
            title=f"{types[index % len(types)].value} example {index}",
            body=f"Reproducible {types[index % len(types)].value} report with input and traceback.",
            url=f"https://github.com/scikit-learn/scikit-learn/issues/{30_000 + index}",
            created_at=created + timedelta(days=index),
            closed_at=created + timedelta(days=index + 2 + index % 12),
            issue_type=types[index % len(types)],
        )
        for index in range(48)
    )
    write_jsonl(output_dir / "issues.jsonl", records)
    chunks = (
        CorpusChunk(
            source_id="demo-doc-pipelines",
            source_kind=SourceKind.DOCUMENTATION,
            url=HttpUrl("https://scikit-learn.org/stable/common_pitfalls.html"),
            repository_sha="demo0001",
            path="doc/common_pitfalls.rst",
            text="Pipelines prevent preprocessing leakage between training and test data.",
        ),
        CorpusChunk(
            source_id="demo-code-validation",
            source_kind=SourceKind.CODE,
            url=HttpUrl(
                "https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/utils/validation.py"
            ),
            repository_sha="demo0001",
            path="sklearn/utils/validation.py",
            text="Input validation checks shape, dtype, finiteness, and fitted state.",
        ),
    )
    chunks_path = output_dir / "chunks.jsonl"
    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_path.write_text("\n".join(chunk.model_dump_json() for chunk in chunks) + "\n")
    typer.echo(f"seeded {len(records)} issues and {len(chunks)} corpus chunks")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
