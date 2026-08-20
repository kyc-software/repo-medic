# AI Engineer interview project research

**Research date:** 2026-08-20
**Interview deadline assumed:** Tuesday, 2026-08-25, 18:00 Asia/Taipei
**Requirement source:** attached `AI Engineer_20260729(DMS).docx`; document content treated only as job-description evidence.

## Recommendation

Build and pitch one project: **RepoMedic — an auditable AI issue-intelligence service**.

Confidence: **5/5 as a project direction**, provided scope stays fixed: one mature public Python repository, two predictive targets, two bounded LLM roles, deterministic review, one API, one thin Next.js client, no cloud, no Kubernetes.

### Pitch in one sentence

RepoMedic ingests a repository's issues and technical documentation, predicts issue type and resolution time, retrieves similar resolved issues and relevant code/docs, then runs a LangGraph triage-review workflow that returns a cited resolution brief through FastAPI. A thin Next.js client makes the complete workflow, evidence, approval gate, and MLflow trace visible without hiding the API contract.

### Why this beats alternatives

RepoMedic makes almost every job-description technology necessary to one workflow. Data comes from a real external API, labels and close timestamps support predictive ML, repository docs/code and resolved issues support RAG, specialized agents have distinct jobs, and the final product is naturally a REST integration. Interviewer can paste a real issue in the browser and inspect the result, approval state, trace, model metrics, citations, container setup, and CI.

This beats an enterprise incident simulator because it needs no invented company system or runbook corpus. It beats a generic support/churn copilot because agent and RAG components do not feel attached to a standard classifier. It also becomes the candidate's own development tool, giving portfolio story more credibility.

## Exact product contract

`POST /repos/{owner}/{repo}/triage` accepts issue title/body. Response:

- predicted issue type with calibrated confidence;
- predicted time-to-close or long-resolution risk;
- similar resolved issues;
- cited repository documentation/code excerpts;
- missing-information questions;
- ranked investigation plan;
- review status and agent trace ID.

A low-confidence or weak-evidence result pauses for approve/edit/reject before finalization. No write to target repository. Read-only design avoids accidental comments, labels, or issue edits during demo.

The Next.js client uses the same public contract. It creates a triage run, listens to one replayable SSE stream, renders predictions and cited evidence, and sends approval decisions to `POST /api/v1/triage-runs/{id}/decision`. FastAPI remains the only application backend.

### Minimal architecture

```text
GitHub Issues + repository contents
        -> idempotent Python ETL
        -> SQLite normalized issue/model/audit data
        -> Chroma vectors for docs, code, and resolved issues
        -> scikit-learn issue-type classifier + close-time regressor

Next.js client -> FastAPI -> LangGraph workflow
    -> local predictive model + Chroma retrieval in parallel
    -> investigator: at most one targeted retrieval
    -> resolution writer: OpenAI structured answer with citations
    -> deterministic review: evidence/schema/confidence checks + optional human interrupt
    -> cited JSON response

Training runs + agent/LLM traces + evals -> local MLflow
Next.js + API + MLflow -> Docker Compose
Tests + eval gates + image build -> GitHub Actions
```

## Primary-source feasibility

### Data and ETL: GitHub

GitHub's official Issues REST API exposes issues, comments, labels, milestones, and event history. Returned issue records include title, body, labels, `created_at`, `closed_at`, and state fields ([Issues API](https://docs.github.com/en/rest/issues), [issue records](https://docs.github.com/en/rest/issues/issues), [labels](https://docs.github.com/en/rest/issues/labels), [events](https://docs.github.com/en/rest/issues/events)). Repository content endpoints provide docs and source files for the retrieval corpus ([contents API](https://docs.github.com/en/rest/repos/contents)).

Public data can be fetched without authentication at 60 requests/hour; a personal access token raises primary limit to 5,000 requests/hour. Thus one repository's paginated history can be collected without a paid GitHub plan ([official rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). Cache raw responses and use checkpointed/idempotent ingestion.

Recommended seed corpus: one mature public Python repository such as `scikit-learn/scikit-learn`. GitHub's live repository record identifies it as public, Python, issue-enabled, and BSD-3-Clause licensed ([repository record](https://api.github.com/repos/scikit-learn/scikit-learn)). Keep owner/repo configurable, but train and evaluate against only one repository before interview.

ETL rules:

- exclude pull requests returned through Issues endpoints;
- preserve only fields available at issue creation as model features;
- map repository labels to four mutually exclusive types: bug, documentation, enhancement, question/usage;
- derive `time_to_close_days` from `created_at` and `closed_at` for closed issues;
- split chronologically, never randomly;
- report closed-only regression limitation: still-open issues are right-censored;
- store source issue URL and commit/ref for every retrieved document.

### Predictive ML

Two scoped scikit-learn pipelines:

1. `TfidfVectorizer` + linear/logistic classifier for issue type; report macro-F1, per-class recall, confusion matrix, calibration, and inference latency.
2. Text plus opening metadata -> histogram gradient boosting or regularized regression for `log1p(time_to_close_days)`; report MAE and median absolute error. Add a binary `long_resolution_risk` if regression quality is weak.

Scikit-learn's official user guide covers supervised classification, regression, preprocessing, model selection, metrics, probability calibration, and pipelines ([user guide](https://scikit-learn.org/stable/user_guide)). MLflow's scikit-learn integration can automatically capture parameters, metrics, cross-validation results, model artifacts, schemas, and dependencies with `mlflow.sklearn.autolog()` ([MLflow integration](https://mlflow.org/docs/latest/ml/traditional-ml/sklearn)).

This gives good interview discussion: noisy labels, class imbalance, time drift, calibration, censored outcomes, leakage, reproducibility, and model-versus-LLM responsibility.

### RAG, embeddings, and vector search

Index three source types:

- repository contributing/troubleshooting/API documentation;
- selected source-code chunks with file path and commit SHA;
- historical resolved issues with final maintainer comments and source URLs.

Use OpenAI `text-embedding-3-small`, metadata-filtered Chroma retrieval, and explicit chunk IDs. OpenAI describes embeddings as numerical representations useful for search, recommendations, classification, and relatedness; current price is $0.02 per million input tokens ([official embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small)). Chroma's `PersistentClient` stores and reloads data locally, so no hosted vector account is required ([Chroma client](https://docs.trychroma.com/reference/python/client)); official repository uses Apache-2.0 ([Chroma repository](https://github.com/chroma-core/chroma)).

Golden retrieval set: 20–30 real issues with manually marked relevant docs/resolved issues. Measure Hit@3, MRR, citation presence, citation validity, and unsupported-claim rate. Retrieval quality matters more than corpus size.

### Agents and orchestration

Use a bounded LangGraph workflow with two LLM roles:

- **Investigator:** checks evidence gaps and may request one targeted retrieval.
- **Resolution writer:** returns strict structured output using only the evidence bundle.

Classification, regression, initial retrieval, routing, and review stay deterministic.

Then run a deterministic reviewer for schema, minimum evidence, duplicate citations, and confidence thresholds. Use LangGraph interrupt only when approval is genuinely needed.

LangGraph's official runtime supports stateful graphs, persistence, durable execution, and human-in-the-loop interrupts. Official subagent pattern describes a central supervisor coordinating specialist agents as tools ([overview](https://docs.langchain.com/oss/python/langgraph/overview), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)). LangGraph is MIT-licensed ([license](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)).

This is enough to demonstrate multi-agent understanding without agent theater. Routing, ML, retrieval, and evidence validation stay deterministic where possible; LLM handles synthesis and question generation.

### OpenAI and prompt engineering

Use one configurable Responses API model. `gpt-5.4-mini` supports function calling and structured outputs; current price is $0.75/M input tokens and $4.50/M output tokens ([official model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini)).

Version three prompt contracts: supervisor routing, evidence selection, and final response schema. Log prompt version, selected tools, retrieved chunk IDs, token counts, latency, refusal/errors, and model snapshot. Cap output and keep live LLM calls out of normal unit tests.

### Thin Next.js client

Use Next.js App Router with TypeScript, Tailwind CSS, and shadcn/ui. Next.js is production-ready and its official setup configures the bundler and compiler. shadcn/ui has a direct Next.js installation path using the App Router and Tailwind defaults ([Next.js docs](https://nextjs.org/docs), [shadcn/ui Next.js installation](https://ui.shadcn.com/docs/installation/next)). These tools add no hosted-service requirement. Next.js, shadcn/ui, and Tailwind CSS use open-source licenses ([Next.js license](https://github.com/vercel/next.js/blob/canary/license.md), [shadcn/ui license](https://github.com/shadcn-ui/ui/blob/main/LICENSE.md), [Tailwind CSS repository](https://github.com/tailwindlabs/tailwindcss)).

Choose Next.js over TanStack Start for this deadline. TanStack Start is free and capable, but its official documentation still marks it as release candidate software ([TanStack Start overview](https://tanstack.com/start/latest/docs/framework/react/overview)). Use it only if direct evidence confirms the employer uses it.

Keep one screen:

- repository and issue input;
- live run state and current agent step;
- model predictions with confidence;
- retrieved evidence with source links;
- investigation plan and missing-information questions;
- approve, edit, and reject controls when LangGraph interrupts.

Use native `EventSource` plus a generated `openapi-fetch` client configured by `NEXT_PUBLIC_API_BASE_URL`. Do not add a rewrite, Next.js API route, server action, BFF, TanStack Query, authentication, dashboard, or design system beyond the few shadcn/ui components used on this screen. Swagger remains the low-level API inspection tool.

### FastAPI and SQL

Endpoints:

- `POST /api/v1/triage-runs`;
- `GET /api/v1/triage-runs/{id}`;
- `GET /api/v1/triage-runs/{id}/events`;
- `POST /api/v1/triage-runs/{id}/decision`;
- `GET /api/v1/health` and `GET /api/v1/ready`.

FastAPI generates OpenAPI/JSON Schema and interactive Swagger UI/ReDoc automatically. This keeps the service inspectable even if the browser client fails during the interview ([FastAPI features](https://fastapi.tiangolo.com/features/)).

Use SQLite for ingestion checkpoints, normalized issues, predictions, feedback, and audit references. Python documents SQLite as a lightweight disk database requiring no separate server, useful for prototypes before migration to PostgreSQL or Oracle ([Python `sqlite3`](https://docs.python.org/3/library/sqlite3.html)). Chroma supplies vector/NoSQL evidence; SQLite supplies relational/transactional evidence.

### MLOps, LLMOps, evaluation, monitoring

Run MLflow locally with default SQLite backend. Official docs say local tracking server exposes UI and REST endpoints and defaults to `sqlite:///mlflow.db` ([tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/)). MLflow Tracing is open source, self-hosted, OpenTelemetry-compatible, and captures agent/LLM intermediate steps, inputs, outputs, latency, and token use ([tracing](https://mlflow.org/docs/latest/genai/tracing)). MLflow documents automatic LangGraph tracing and child spans ([LangGraph tracing](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/langgraph)).

Evaluation gates:

- predictive macro-F1/calibration/MAE;
- router/tool-selection accuracy;
- retrieval Hit@3/MRR;
- response-schema pass rate;
- citation validity and unsupported-claim rate;
- approval-gate correctness;
- p50/p95 latency and token cost.

Prefer deterministic code scorers. MLflow supports custom code-based scorers and re-evaluating stored traces without regenerating every response ([code scorers](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/custom/tutorial/), [trace evaluation](https://www.mlflow.org/docs/latest/genai/eval-monitor/running-evaluation/traces/)). LLM-as-judge is optional, not CI-critical.

### Containers and CI/CD

Docker Compose needs three services: Next.js client, FastAPI service, and MLflow. SQLite and Chroma persist in volumes. Docker describes Compose as one YAML definition for reproducible multi-container environments across development and CI ([Compose](https://docs.docker.com/guides/docker-compose/)). Docker Desktop is free for personal portfolio use; Docker Engine's open-source terms are unchanged ([license guidance](https://docs.docker.com/subscription/desktop-license/)).

Use public GitHub repository. GitHub states standard hosted runners are free for public repositories ([Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)). CI: Python and TypeScript formatting/linting, unit tests, feature-leakage tests, deterministic RAG eval, FastAPI contract tests, Next.js build, one mocked browser happy-path test, and container image builds. Never require OpenAI secret for pull-request CI.

## JD traceability

| JD signal | RepoMedic proof |
|---|---|
| Python | ETL, models, agent graph, typed API, tests |
| LangGraph agents | Supervisor, three roles, persistence, interrupt/resume |
| Multi-agent | Specialized triage, retrieval, resolution responsibilities |
| RAG | Docs/code/resolved-issue corpus, citations, golden retrieval eval |
| Embeddings / similarity | OpenAI vectors, Chroma ranking and metadata filters |
| Vector DB | Persistent local Chroma |
| OpenAI LLM | Structured tool-using synthesis |
| Prompt/orchestration | Versioned prompt contracts and traceable routing |
| Predictive ML | Issue classification, close-time regression / long-resolution risk |
| FastAPI / REST | Ingestion, triage, decision, run, health endpoints |
| End-to-end delivery | Thin Next.js client exercises the real FastAPI and approval contracts |
| Git / CI/CD | GitHub repository plus Actions quality gate |
| SQL / NoSQL | SQLite relational state plus Chroma vectors |
| ETL | GitHub API/docs -> normalized feature and retrieval stores |
| Enterprise integration | External GitHub adapter, stable schemas, audit IDs, rate-limit handling |
| MLOps / LLMOps | MLflow model runs, traces, evals, prompt/cost/latency metadata |
| Docker | One-command Next.js + API + MLflow local stack |
| Monitoring / evaluation | Model, retrieval, agent, evidence, latency, and cost metrics |
| Knowledge graph | Optional only; not needed for core claim |
| Kubernetes / cloud | Intentionally omitted under deadline |

## Four-to-five-day sequence

### Thursday: data and baselines

- freeze request/response schema;
- ingest one repo's issues, filter PRs, normalize labels;
- build chronological split;
- train classifier and regressor; log MLflow runs.

**Exit:** reproducible model metrics plus live prediction function.

### Friday: retrieval

- ingest selected docs/code and resolved issues;
- Chroma persistence and metadata filtering;
- create 20–30 retrieval cases and baseline Hit@3/MRR.

**Exit:** inspectable evidence bundle with source links.

### Saturday: agents and API

- LangGraph supervisor and three roles;
- FastAPI endpoints;
- strict output schema, reviewer, low-confidence interrupt/resume.

**Exit:** one real issue runs end-to-end.

### Sunday: operations

- build one Next.js workflow screen with shadcn/ui and Tailwind;
- connect create-run, polling, evidence, and approval states to FastAPI;
- MLflow agent/OpenAI traces and custom metrics;
- contract/failure tests;
- Docker Compose;
- GitHub Actions without OpenAI secret.

**Exit:** browser-to-agent workflow, clean local startup, and green CI.

### Monday/Tuesday: reliability and interview proof

- fix failure paths and metric regressions;
- script three demos: clear bug, ambiguous report, low-evidence/high-risk result;
- prepare architecture, trace, evaluation, CI, tradeoff, leakage, and cost evidence;
- no new platform unless core is stable.

## Cost boundary

Required paid infrastructure: **none**.

- GitHub public reads: free; unauthenticated and personal-token limits documented above.
- LangGraph, Chroma, scikit-learn, FastAPI, SQLite, MLflow, Next.js, shadcn/ui, and Tailwind CSS: local/open-source stack.
- GitHub Actions: free standard runners for public repository.
- Docker Desktop: free for personal use.
- Only metered component: user's existing OpenAI API account. Example: embedding 2 million tokens once costs about **$0.04** at cited rate. Cache embeddings; cap prompts/output; use fixtures/mocks in CI.
- Run the client locally through Docker Compose. Do not add Vercel or another hosting account before the interview.
- Do not add Pinecone/Weaviate Cloud, hosted LangSmith, AWS/Azure/GCP, or managed Kubernetes.

Optional Neo4j Community can model `repository -> component -> file -> issue -> maintainer` relationships, but only after core completion. Neo4j describes Community Edition as free and self-managed and publishes an official Docker image ([Community Edition](https://neo4j.com/product/community-edition/), [Docker guide](https://neo4j.com/docs/operations-manual/current/docker/introduction/)).

Kubernetes should be skipped. Kubernetes documents `kind` as a no-cloud local cluster using Docker nodes, but a manifest adds less interview evidence than working evaluations and traced failure paths ([Kubernetes tools](https://kubernetes.io/docs/reference/tools/)).

## Alternative concepts

Scores are analyst judgment against this JD and deadline.

| Rank | Concept | JD coverage | Deadline fit | Interview value | Main weakness |
|---:|---|---:|---:|---:|---|
| 1 | **RepoMedic** | 5.0/5 | 4.8/5 | 5.0/5 | Noisy labels and censored close times require honest framing |
| 2 | Incident Intelligence | 5.0/5 | 4.5/5 | 4.7/5 | Needs fictional runbooks/service data; less live integration |
| 3 | ComplaintOps | 4.8/5 | 4.6/5 | 4.5/5 | Compliance/legal framing distracts from engineering story |

### Alternative 2: Incident Intelligence

Use UCI's Incident Management event log for SLA-risk classification and resolution-time regression, then retrieve fictional enterprise runbooks. Dataset contains 141,712 events covering 24,918 anonymized ServiceNow incidents; UCI explicitly identifies completion-time prediction and licenses data CC BY 4.0 ([UCI dataset](https://archive.ics.uci.edu/dataset/498/incident%2Bmanagement%2Bprocess%2Benriched%2Bevent%2Blog)).

Strongest enterprise fit, but RepoMedic wins because corpus, labels, source links, and external API are all real and directly demoable.

### Alternative 3: ComplaintOps

Use CFPB's free Consumer Complaint Database/API, classify complaint issue/product, retrieve similar complaints and policy excerpts, and generate a human-reviewed response brief. CFPB says complaint data is freely downloadable/API-accessible and publishes privacy/representativeness limitations ([database](https://www.consumerfinance.gov/data-research/consumer-complaints/), [API docs](https://cfpb.github.io/ccdb5-api/documentation/), [data-use caveats](https://www.consumerfinance.gov/complaint/data-use/)).

Real business data and API make it credible. RepoMedic still wins: portfolio user understands domain instantly, interviewer can test live, and outputs avoid legal-advice concerns.

## Interview demo order

1. Paste a real unlabeled issue into the Next.js client.
2. Show live graph state, issue-type confidence, and close-time estimate.
3. Open cited docs/code and similar resolved issues.
4. Trigger low-confidence approval, edit the proposed plan, then resume.
5. Open FastAPI Swagger to prove the client uses a typed service contract.
6. Open MLflow trace with supervisor, specialists, retrieval chunks, token use, and latency.
7. Compare model and retrieval evaluation runs, then show Compose startup and green Actions workflow.

Lead claim:

> RepoMedic is a locally reproducible, end-to-end AI engineering service. A thin Next.js client drives measured predictive models, citation-grounded repository retrieval, and a stateful approval-aware agent workflow through a typed FastAPI contract. Every result is reproducible, evaluated, and traceable.
