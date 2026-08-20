import createClient from "openapi-fetch";

import type { paths } from "./generated";
import type { IssueSubmission, ReviewDecision, RunAccepted, TriageRun } from "./types";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const client = createClient<paths>({ baseUrl });

export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function createTriageRun(submission: IssueSubmission): Promise<RunAccepted> {
  const { data, error, response } = await client.POST("/api/v1/triage-runs", {
    body: submission,
  });
  if (!data) {
    throw new ApiError(`Create failed (${response.status}): ${JSON.stringify(error)}`);
  }
  return data;
}

export async function getTriageRun(runId: string): Promise<TriageRun> {
  const { data, error, response } = await client.GET("/api/v1/triage-runs/{run_id}", {
    params: { path: { run_id: runId } },
  });
  if (!data) {
    throw new ApiError(`Snapshot failed (${response.status}): ${JSON.stringify(error)}`);
  }
  return data;
}

export async function decideTriageRun(
  runId: string,
  decision: ReviewDecision,
): Promise<void> {
  const { error, response } = await client.POST("/api/v1/triage-runs/{run_id}/decision", {
    params: { path: { run_id: runId } },
    body: decision,
  });
  if (!response.ok) {
    throw new ApiError(`Decision failed (${response.status}): ${JSON.stringify(error)}`);
  }
}
