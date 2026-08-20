# RepoMedic delivery plan

## Build order

- [x] Phase 0 — Bun/Next and uv/FastAPI workspace, relocated source notes, Git, hooks, CI skeleton.
- [x] Phase 1 — discriminated domain, SQLite lifecycle, REST/SSE, OpenAPI-generated browser types.
- [x] Phase 2 — GitHub issue ETL, label mapping, chronological sklearn training, baselines, MLflow artifacts.
- [x] Phase 3 — content-hash OpenAI embedding cache, persistent Chroma adapter, 20-case golden retrieval set and deterministic metrics.
- [x] Phase 4 — parallel LangGraph execution, two bounded roles, deterministic review, atomic ordered events, replay and decision resume.
- [x] Phase 5 — one-screen shadcn client with form, progress, predictions, evidence, cited brief, and review controls.
- [x] Phase 6 — Compose, CI, quickstart, limitations, fixtures, and demo script.

## Exit gates

Phase gates are executable repository commands, not prose claims:

| Gate | Command |
| --- | --- |
| Static quality | `bun run check` |
| Type contracts | `bun run typecheck` |
| Unit/integration | `bun run test` |
| Contract drift | `bun run contract:check` |
| Production web | `bun run build` |
| Complete gate | `bun run verify` |
| Local demo | `bun run dev` |
| Container demo | `bun run compose:up` |

Tests and CI stay in demo mode and never call GitHub or OpenAI.

## Interview workflow

1. Start in demo mode and show `/docs` OpenAPI plus one browser screen.
2. Submit clear bug fixture. Explain prediction/retrieval parallelism and two-request browser budget.
3. Open citations and show source IDs, SHA, score, and model versions.
4. Submit ambiguous fixture containing “unclear” or “maybe.” Approve or edit at deterministic review interrupt.
5. Show ordered SQLite events, LangGraph checkpoint boundary, MLflow experiment, model/retrieval metrics, and test protecting atomic terminal event delivery.
6. Explain production replacements—durable worker, Postgres, hosted vector store—without implementing deadline-driven infrastructure.

## Remaining rehearsal work

- Run live ingestion/training/indexing once with personal GitHub token and existing OpenAI key.
- Replace draft golden source IDs only where actual corpus chunk IDs differ.
- Record achieved model and retrieval metrics in `docs/ml-metrics.md`.
- Freeze demo inputs and rehearse recovery from missing secret, model, or corpus.
