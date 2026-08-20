import type { RunEvent, RunEventKind, RunningPhase, TriageRun } from "./types";

export const RUN_EVENT_KINDS = [
  "run.queued",
  "run.phase",
  "review.required",
  "run.completed",
  "run.rejected",
  "run.failed",
] satisfies RunEventKind[];
const EVENT_KINDS: ReadonlySet<string> = new Set(RUN_EVENT_KINDS);
const RUN_STATUSES: ReadonlySet<string> = new Set([
  "queued",
  "running",
  "awaiting_review",
  "completed",
  "rejected",
  "failed",
]);

function isEventKind(value: unknown): value is RunEventKind {
  return isString(value) && EVENT_KINDS.has(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isSubmission(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.client_request_id) &&
    isString(value.title) &&
    isString(value.body)
  );
}

function isPrediction(value: unknown): boolean {
  return (
    isRecord(value) &&
    ["bug", "documentation", "feature", "question"].includes(String(value.issue_type)) &&
    typeof value.calibrated_confidence === "number" &&
    typeof value.predicted_close_days === "number" &&
    isString(value.classifier_version) &&
    isString(value.regressor_version)
  );
}

function isEvidence(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.source_id) &&
    ["documentation", "code", "resolved_issue"].includes(String(value.source_kind)) &&
    isString(value.url) &&
    isString(value.repository_sha) &&
    isString(value.excerpt) &&
    typeof value.score === "number"
  );
}

function isBrief(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.summary) &&
    isStringArray(value.missing_information) &&
    isStringArray(value.citation_ids) &&
    Array.isArray(value.investigation_steps) &&
    value.investigation_steps.every(
      (step) =>
        isRecord(step) &&
        typeof step.rank === "number" &&
        isString(step.action) &&
        isString(step.rationale) &&
        isStringArray(step.citation_ids),
    )
  );
}

function isTriageRun(value: unknown): value is TriageRun {
  if (!isRecord(value)) return false;
  if (!isString(value.status) || !RUN_STATUSES.has(value.status)) return false;
  if (
    !isString(value.run_id) ||
    !isSubmission(value.submission) ||
    !isString(value.created_at)
  ) {
    return false;
  }
  if (value.status === "queued") return true;
  if (!isString(value.updated_at)) return false;
  if (value.status === "running") {
    return [
      "predicting",
      "retrieving",
      "investigating",
      "drafting",
      "reviewing",
    ].includes(String(value.phase));
  }
  if (value.status === "rejected") return isString(value.reason);
  if (value.status === "failed") {
    return isString(value.error_code) && typeof value.retryable === "boolean";
  }
  const hasAnalysis =
    isPrediction(value.prediction) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(isEvidence);
  if (value.status === "completed") return hasAnalysis && isBrief(value.brief);
  return hasAnalysis && isBrief(value.draft) && isStringArray(value.review_reasons);
}

export function parseRunEvent(raw: string): RunEvent {
  const parsed: unknown = JSON.parse(raw);
  if (!isRecord(parsed)) throw new Error("SSE event must be an object");
  if (typeof parsed.sequence !== "number" || !Number.isInteger(parsed.sequence)) {
    throw new Error("SSE event has invalid sequence");
  }
  if (!isString(parsed.run_id) || !isString(parsed.timestamp)) {
    throw new Error("SSE event is missing identity fields");
  }
  if (!isEventKind(parsed.kind)) {
    throw new Error("SSE event has unknown kind");
  }
  if (!isRecord(parsed.payload)) throw new Error("SSE event has invalid payload");
  const common = {
    sequence: parsed.sequence,
    run_id: parsed.run_id,
    timestamp: parsed.timestamp,
  };
  if (parsed.kind === "run.queued") {
    if (parsed.payload.status !== "queued")
      throw new Error("SSE queued payload is invalid");
    return { ...common, kind: parsed.kind, payload: { status: "queued" } };
  }
  const snapshot = parsed.payload.snapshot;
  if (!isTriageRun(snapshot)) throw new Error("SSE event contains invalid snapshot");
  if (parsed.kind === "run.phase") {
    if (snapshot.status !== "running" || !isRunningPhase(parsed.payload.phase)) {
      throw new Error("SSE phase payload is invalid");
    }
    return {
      ...common,
      kind: parsed.kind,
      payload: { phase: parsed.payload.phase, snapshot },
    };
  }
  if (parsed.kind === "review.required") {
    if (snapshot.status !== "awaiting_review")
      throw new Error("SSE review payload is invalid");
    return { ...common, kind: parsed.kind, payload: { snapshot } };
  }
  if (parsed.kind === "run.completed") {
    if (snapshot.status !== "completed")
      throw new Error("SSE completion payload is invalid");
    return { ...common, kind: parsed.kind, payload: { snapshot } };
  }
  if (parsed.kind === "run.rejected") {
    if (snapshot.status !== "rejected")
      throw new Error("SSE rejection payload is invalid");
    return { ...common, kind: parsed.kind, payload: { snapshot } };
  }
  if (snapshot.status !== "failed") throw new Error("SSE failure payload is invalid");
  return { ...common, kind: parsed.kind, payload: { snapshot } };
}

function isRunningPhase(value: unknown): value is RunningPhase {
  return (
    value === "predicting" ||
    value === "retrieving" ||
    value === "investigating" ||
    value === "drafting" ||
    value === "reviewing"
  );
}
