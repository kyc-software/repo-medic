import type { components, operations } from "./generated";

export type IssueSubmission = components["schemas"]["IssueSubmission"];
export type RunAccepted = components["schemas"]["RunAccepted"];
export type ResolutionBrief = components["schemas"]["ResolutionBrief"];
export type EvidenceItem = components["schemas"]["EvidenceItem"];
export type PredictionBundle = components["schemas"]["PredictionBundle"];
export type RunningPhase = components["schemas"]["RunningPhase"];
export type ReviewDecision =
  | components["schemas"]["ApproveDecision"]
  | components["schemas"]["EditDecision"]
  | components["schemas"]["RejectDecision"];
export type TriageRun =
  | components["schemas"]["QueuedRun"]
  | components["schemas"]["RunningRun"]
  | components["schemas"]["AwaitingReviewRun"]
  | components["schemas"]["CompletedRun"]
  | components["schemas"]["RejectedRun"]
  | components["schemas"]["FailedRun"];

export type RunEvent =
  operations["stream_events_api_v1_triage_runs__run_id__events_get"]["responses"][200]["content"]["application/json"];
export type RunEventKind = RunEvent["kind"];
