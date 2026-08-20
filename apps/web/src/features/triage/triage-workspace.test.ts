import { describe, expect, it } from "vitest";

import { workspaceReducer } from "./triage-workspace";

describe("workspaceReducer", () => {
  it("ignores replayed or duplicate sequence IDs", () => {
    const accepted = workspaceReducer(
      { status: "idle" },
      { type: "accepted", runId: "run", eventsUrl: "http://localhost/events" },
    );
    const first = workspaceReducer(accepted, {
      type: "event",
      event: {
        sequence: 2,
        run_id: "run",
        kind: "run.queued",
        timestamp: "now",
        payload: { status: "queued" },
      },
    });
    const replay = workspaceReducer(first, {
      type: "event",
      event: {
        sequence: 2,
        run_id: "run",
        kind: "run.queued",
        timestamp: "now",
        payload: { status: "queued" },
      },
    });
    expect(replay).toEqual(first);
  });
});
