# RepoMedic

RepoMedic is a local-first, evidence-backed issue-triage demo for `scikit-learn/scikit-learn`. It combines chronological predictive ML, Chroma retrieval, two bounded OpenAI roles, LangGraph, human review, FastAPI/SSE, and one Next.js screen.

For the shortest setup, read [Start and use RepoMedic](docs/getting-started.md).

## Quickstart: free demo mode

Prerequisites: Bun 1.3.14, uv 0.12.5, and Python 3.12.

```bash
cp .env.example .env
bun install
uv sync --project apps/api --all-groups
bun run dev
```

Open:

- Web: <http://localhost:3000>
- FastAPI/Swagger: <http://localhost:8000/docs>
- MLflow: <http://localhost:5001>

Demo mode runs real API, SQLite, SSE, LangGraph, review policy, and UI with deterministic ML/RAG/LLM adapters. No API call or paid service occurs.

## Live data and model path

```bash
uv run --project apps/api repomedic ingest --limit 5000
uv run --project apps/api repomedic build-corpus
uv run --project apps/api repomedic train
uv run --project apps/api repomedic index
uv run --project apps/api repomedic evaluate
uv run --project apps/api repomedic evaluate-retrieval
REPOMEDIC_MODE=live bun run dev
```

`ingest` uses GitHub pagination, conditional ETag page cache, rate-limit reset handling, pull-request exclusion, and idempotent issue numbers. Public GitHub access works without a token at lower limits. `index` and live runs require existing `OPENAI_API_KEY`; embedding vectors cache by content hash.

## Verification

```bash
bun run verify
docker compose up --build
```

Pre-commit fixes only staged Biome/Ruff files. Pre-push runs full verification. CI needs no OpenAI or GitHub secret.

## Demo inputs

- Clear: “Pipeline raises validation error after dtype conversion” with reproducible body.
- Review: include “unclear,” “maybe,” or “sometimes” to lower deterministic confidence.
- Insufficient evidence: include “no evidence” to trigger evidence review.

## Honest limitations

- One repository only; current labels are a noisy target.
- Close-time training uses closed issues only. Open issues are right-censored.
- SQLite, embedded Chroma, and in-process tasks prove seams, not horizontal scale.
- Unexpected restart marks queued/running work retryable-failed; review waits survive.
- Live corpus metrics depend on one explicit ingestion/training/indexing run and should be recorded before interview.
- No GitHub writes, auth, dashboard, cloud, or decorative architecture.

See [architecture](docs/architecture.md), [delivery plan](docs/plan.md), [research](docs/research.md), and [ML metric notes](docs/ml-metrics.md).
