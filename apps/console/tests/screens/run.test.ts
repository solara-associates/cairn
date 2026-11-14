import { describe, expect, it, vi } from "vitest";
import { pollRun } from "../../src/screens/run";
import { AssessmentRunSummary } from "../../src/api";

function summary(state: string): AssessmentRunSummary {
  return { run_id: "r-1", state, coverage: state === "COMPLETED" ? 1 : 0.5, completed_stages: [], pending_stages: [], failures: [] };
}

describe("pollRun", () => {
  it("returns as soon as the run reaches a terminal state", async () => {
    const getRun = vi
      .fn<[], Promise<AssessmentRunSummary>>()
      .mockResolvedValueOnce(summary("RUNNING"))
      .mockResolvedValueOnce(summary("CHECKPOINTED"))
      .mockResolvedValueOnce(summary("COMPLETED"));

    const updates: string[] = [];
    const run = await pollRun(getRun, {
      intervalMs: 0,
      onUpdate: (r) => updates.push(r.state),
    });

    expect(run.state).toBe("COMPLETED");
    expect(getRun).toHaveBeenCalledTimes(3);
    expect(updates).toEqual(["RUNNING", "CHECKPOINTED", "COMPLETED"]);
  });

  it("stops polling and reports a FAILED run as terminal", async () => {
    const getRun = vi.fn().mockResolvedValue(summary("FAILED"));

    const run = await pollRun(getRun, { intervalMs: 0 });

    expect(run.state).toBe("FAILED");
    expect(getRun).toHaveBeenCalledTimes(1);
  });

  it("raises after maxAttempts if the run never reaches a terminal state", async () => {
    const getRun = vi.fn().mockResolvedValue(summary("RUNNING"));

    await expect(pollRun(getRun, { intervalMs: 0, maxAttempts: 3 })).rejects.toThrow(
      /did not reach a terminal state/,
    );
    expect(getRun).toHaveBeenCalledTimes(3);
  });
});
