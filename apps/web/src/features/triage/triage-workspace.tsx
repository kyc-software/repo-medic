"use client";

import {
  AlertCircleIcon,
  CheckCircle2Icon,
  CircleDotIcon,
  Clock3Icon,
  ExternalLinkIcon,
  GitPullRequestArrowIcon,
  LoaderCircleIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { type FormEvent, useEffect, useReducer, useRef, useState } from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { createTriageRun, decideTriageRun } from "@/lib/api/client";
import { parseRunEvent, RUN_EVENT_KINDS } from "@/lib/api/events";
import type { ResolutionBrief, RunEvent, TriageRun } from "@/lib/api/types";

type WorkspaceState =
  | { status: "idle" }
  | { status: "submitting" }
  | {
      status: "streaming";
      runId: string;
      eventsUrl: string;
      snapshot?: TriageRun;
      sequence: number;
    }
  | { status: "settled"; snapshot: TriageRun; sequence: number }
  | { status: "error"; message: string };

type WorkspaceAction =
  | { type: "submit" }
  | { type: "accepted"; runId: string; eventsUrl: string }
  | { type: "event"; event: RunEvent }
  | { type: "error"; message: string }
  | { type: "reset" };

export function workspaceReducer(
  state: WorkspaceState,
  action: WorkspaceAction,
): WorkspaceState {
  if (action.type === "submit") return { status: "submitting" };
  if (action.type === "accepted") {
    return {
      status: "streaming",
      runId: action.runId,
      eventsUrl: action.eventsUrl,
      sequence: 0,
    };
  }
  if (action.type === "error") return { status: "error", message: action.message };
  if (action.type === "reset") return { status: "idle" };
  if (state.status !== "streaming" || action.event.sequence <= state.sequence)
    return state;
  const eventSnapshot =
    "snapshot" in action.event.payload ? action.event.payload.snapshot : undefined;
  const snapshot = eventSnapshot ?? state.snapshot;
  if (snapshot && ["completed", "rejected", "failed"].includes(snapshot.status)) {
    return { status: "settled", snapshot, sequence: action.event.sequence };
  }
  return { ...state, snapshot, sequence: action.event.sequence };
}

const initialTitle = "Pipeline raises validation error after dtype conversion";
const initialBody =
  "After fitting a Pipeline, predict raises when input changes from float64 to float32. " +
  "The failure is reproducible with the same shape and no missing values.";

export function TriageWorkspace() {
  const [state, dispatch] = useReducer(workspaceReducer, { status: "idle" });
  const [title, setTitle] = useState(initialTitle);
  const [body, setBody] = useState(initialBody);
  const [editedSummary, setEditedSummary] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);
  const eventsUrl = state.status === "streaming" ? state.eventsUrl : null;

  useEffect(() => {
    if (!eventsUrl) return;
    const source = new EventSource(eventsUrl);
    eventSourceRef.current = source;
    const onEvent = (message: MessageEvent<string>) => {
      try {
        const event = parseRunEvent(message.data);
        dispatch({ type: "event", event });
        if (["run.completed", "run.rejected", "run.failed"].includes(event.kind)) {
          source.close();
        }
      } catch (error) {
        source.close();
        dispatch({ type: "error", message: errorMessage(error) });
      }
    };
    for (const eventKind of RUN_EVENT_KINDS) source.addEventListener(eventKind, onEvent);
    return () => source.close();
  }, [eventsUrl]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    eventSourceRef.current?.close();
    dispatch({ type: "submit" });
    try {
      const accepted = await createTriageRun({
        client_request_id: crypto.randomUUID(),
        title,
        body,
      });
      dispatch({
        type: "accepted",
        runId: accepted.run_id,
        eventsUrl: accepted.events_url,
      });
    } catch (error) {
      dispatch({ type: "error", message: errorMessage(error) });
    }
  }

  async function decide(kind: "approve" | "edit" | "reject") {
    const snapshot = currentSnapshot(state);
    if (snapshot?.status !== "awaiting_review") return;
    try {
      if (kind === "approve") await decideTriageRun(snapshot.run_id, { kind: "approve" });
      if (kind === "reject") {
        await decideTriageRun(snapshot.run_id, {
          kind: "reject",
          reason: "Rejected during human review",
        });
      }
      if (kind === "edit") {
        const brief: ResolutionBrief = {
          ...snapshot.draft,
          summary: editedSummary.trim() || snapshot.draft.summary,
        };
        await decideTriageRun(snapshot.run_id, { kind: "edit", brief });
      }
    } catch (error) {
      dispatch({ type: "error", message: errorMessage(error) });
    }
  }

  const snapshot = currentSnapshot(state);
  const busy = state.status === "submitting" || state.status === "streaming";

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-8 px-5 py-8 md:px-8 md:py-12">
      <header className="flex flex-col gap-4 border-b pb-7 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <GitPullRequestArrowIcon className="size-4" />
            scikit-learn/scikit-learn · local-first demo
          </div>
          <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">RepoMedic</h1>
          <p className="max-w-2xl text-balance text-muted-foreground">
            Predict issue type and close time, retrieve repository evidence, then produce
            a cited triage brief.
          </p>
        </div>
        <Badge variant="outline" className="gap-1.5">
          <ShieldCheckIcon /> Human review enforced
        </Badge>
      </header>

      <section className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Issue submission</CardTitle>
            <CardDescription>
              One configured public repository. No GitHub writes.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={submit}>
              <label htmlFor="issue-title" className="grid gap-1.5 text-sm font-medium">
                Title
                <Input
                  id="issue-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  minLength={4}
                  maxLength={300}
                  required
                />
              </label>
              <label htmlFor="issue-body" className="grid gap-1.5 text-sm font-medium">
                Body
                <Textarea
                  id="issue-body"
                  className="min-h-44 resize-y"
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  minLength={10}
                  maxLength={20000}
                  required
                />
              </label>
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={busy}>
                  {busy ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <CircleDotIcon />
                  )}
                  {busy ? "Triage running" : "Run triage"}
                </Button>
                {state.status !== "idle" && !busy ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => dispatch({ type: "reset" })}
                  >
                    Reset
                  </Button>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-6" aria-live="polite">
          <RunStatus state={state} snapshot={snapshot} />
          {snapshot &&
          (snapshot.status === "completed" || snapshot.status === "awaiting_review") ? (
            <>
              <PredictionCard snapshot={snapshot} />
              <BriefCard
                brief={snapshot.status === "completed" ? snapshot.brief : snapshot.draft}
              />
              <EvidenceCard evidence={snapshot.evidence} />
            </>
          ) : null}
          {snapshot?.status === "awaiting_review" ? (
            <ReviewCard
              snapshot={snapshot}
              editedSummary={editedSummary}
              setEditedSummary={setEditedSummary}
              decide={decide}
            />
          ) : null}
        </div>
      </section>
    </main>
  );
}

function currentSnapshot(state: WorkspaceState): TriageRun | undefined {
  if (state.status === "streaming") return state.snapshot;
  if (state.status === "settled") return state.snapshot;
  return undefined;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected failure";
}

function RunStatus({ state, snapshot }: { state: WorkspaceState; snapshot?: TriageRun }) {
  if (state.status === "idle") {
    return (
      <Alert>
        <CircleDotIcon />
        <AlertTitle>Ready</AlertTitle>
        <AlertDescription>
          Submit one issue to start the tracked workflow.
        </AlertDescription>
      </Alert>
    );
  }
  if (state.status === "error") {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon />
        <AlertTitle>Run failed</AlertTitle>
        <AlertDescription>{state.message}</AlertDescription>
      </Alert>
    );
  }
  if (snapshot?.status === "failed") {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon />
        <AlertTitle>{snapshot.error_code}</AlertTitle>
        <AlertDescription>
          {snapshot.retryable ? "Retryable failure." : "Manual intervention required."}
        </AlertDescription>
      </Alert>
    );
  }
  if (snapshot?.status === "rejected") {
    return (
      <Alert>
        <AlertCircleIcon />
        <AlertTitle>Run rejected</AlertTitle>
        <AlertDescription>{snapshot.reason}</AlertDescription>
      </Alert>
    );
  }
  if (snapshot?.status === "completed") {
    return (
      <Alert>
        <CheckCircle2Icon />
        <AlertTitle>Triage completed</AlertTitle>
        <AlertDescription>
          Predictions, evidence, and brief persisted with this run.
        </AlertDescription>
      </Alert>
    );
  }
  if (snapshot?.status === "awaiting_review") {
    return (
      <Alert>
        <AlertCircleIcon />
        <AlertTitle>Human review required</AlertTitle>
        <AlertDescription>{snapshot.review_reasons.join(" · ")}</AlertDescription>
      </Alert>
    );
  }
  const phase = snapshot?.status === "running" ? snapshot.phase : "queued";
  return (
    <Alert>
      <LoaderCircleIcon className="animate-spin" />
      <AlertTitle>Workflow active</AlertTitle>
      <AlertDescription>{phase.replaceAll("_", " ")}</AlertDescription>
    </Alert>
  );
}

function PredictionCard({
  snapshot,
}: {
  snapshot: Extract<TriageRun, { status: "completed" | "awaiting_review" }>;
}) {
  const prediction = snapshot.prediction;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Predictive ML</CardTitle>
        <CardDescription>Features available when issue opens only.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <Metric label="Issue type" value={prediction.issue_type} />
        <Metric
          label="Confidence"
          value={`${Math.round(prediction.calibrated_confidence * 100)}%`}
        />
        <Metric
          label="Predicted close"
          value={`${prediction.predicted_close_days.toFixed(1)} days`}
        />
        <p className="sm:col-span-3 font-mono text-xs text-muted-foreground">
          {prediction.classifier_version} · {prediction.regressor_version}
        </p>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium capitalize">{value}</div>
    </div>
  );
}

function BriefCard({ brief }: { brief: ResolutionBrief }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Resolution brief</CardTitle>
        <CardDescription>{brief.summary}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="space-y-3">
          {brief.investigation_steps.map((step) => (
            <li key={step.rank} className="grid grid-cols-[1.75rem_1fr] gap-2">
              <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">
                {step.rank}
              </span>
              <div>
                <p className="font-medium">{step.action}</p>
                <p className="mt-1 text-sm text-muted-foreground">{step.rationale}</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {step.citation_ids.join(", ")}
                </p>
              </div>
            </li>
          ))}
        </ol>
        <div>
          <p className="text-sm font-medium">Missing information</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {brief.missing_information.join(" · ") || "None"}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceCard({
  evidence,
}: {
  evidence: Extract<TriageRun, { status: "completed" | "awaiting_review" }>["evidence"];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Retrieved evidence</CardTitle>
        <CardDescription>
          Every item carries source identity and repository version.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Accordion>
          {evidence.map((item) => (
            <AccordionItem key={item.source_id} value={item.source_id}>
              <AccordionTrigger>
                <span className="flex min-w-0 items-center gap-2">
                  <Badge variant="secondary">
                    {item.source_kind.replaceAll("_", " ")}
                  </Badge>
                  <span className="truncate">
                    {item.path ?? `Issue #${item.issue_number}`}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {Math.round(item.score * 100)}%
                  </span>
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <p>{item.excerpt}</p>
                <a
                  className="mt-3 inline-flex items-center gap-1 text-xs"
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {item.source_id}
                  <ExternalLinkIcon className="size-3" />
                </a>
                <p className="mt-2 font-mono text-xs text-muted-foreground">
                  SHA {item.repository_sha}
                </p>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </CardContent>
    </Card>
  );
}

function ReviewCard({
  snapshot,
  editedSummary,
  setEditedSummary,
  decide,
}: {
  snapshot: Extract<TriageRun, { status: "awaiting_review" }>;
  editedSummary: string;
  setEditedSummary: (value: string) => void;
  decide: (kind: "approve" | "edit" | "reject") => Promise<void>;
}) {
  return (
    <Card className="border-amber-500/40">
      <CardHeader>
        <CardTitle>Review gate</CardTitle>
        <CardDescription>
          Approve draft, replace summary while retaining attached citations, or reject.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Textarea
          value={editedSummary}
          onChange={(event) => setEditedSummary(event.target.value)}
          placeholder={snapshot.draft.summary}
        />
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => decide("approve")}>
            <CheckCircle2Icon />
            Approve
          </Button>
          <Button variant="outline" onClick={() => decide("edit")}>
            <Clock3Icon />
            Save edit
          </Button>
          <Button variant="destructive" onClick={() => decide("reject")}>
            <AlertCircleIcon />
            Reject
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
