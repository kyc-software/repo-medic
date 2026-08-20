import { describe, expect, it } from "vitest";

import { parseRunEvent } from "./events";

describe("parseRunEvent", () => {
  it("accepts a typed running snapshot", () => {
    const event = parseRunEvent(
      JSON.stringify({
        sequence: 2,
        run_id: "ec3f715d-1d45-4f0e-a54b-387a4e70a19b",
        kind: "run.phase",
        timestamp: "2026-08-20T10:00:00Z",
        payload: {
          phase: "predicting",
          snapshot: {
            status: "running",
            run_id: "ec3f715d-1d45-4f0e-a54b-387a4e70a19b",
            submission: {
              client_request_id: "request-0001",
              title: "Validation fails",
              body: "Stable body long enough",
            },
            phase: "predicting",
            created_at: "2026-08-20T10:00:00Z",
            updated_at: "2026-08-20T10:00:01Z",
          },
        },
      }),
    );
    expect(event.sequence).toBe(2);
    expect("snapshot" in event.payload ? event.payload.snapshot.status : undefined).toBe(
      "running",
    );
  });

  it("rejects malformed terminal snapshots at SSE boundary", () => {
    expect(() =>
      parseRunEvent(
        JSON.stringify({
          sequence: 4,
          run_id: "run",
          kind: "run.completed",
          timestamp: "now",
          payload: {
            snapshot: {
              status: "completed",
              run_id: "run",
              submission: { client_request_id: "request", title: "title", body: "body" },
              created_at: "now",
              updated_at: "now",
            },
          },
        }),
      ),
    ).toThrow("invalid snapshot");
  });
});
