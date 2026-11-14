import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderResults } from "../../src/screens/results";
import { resetSession, setProjectId, setRunId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const RESULTS_BODY = {
  run_id: "run-1",
  coverage: { run_id: "run-1", state: "COMPLETED", total_stages: 6, completed_stages: [], pending_stages: [], coverage: 1, failures: [] },
  resources: [],
  workloads: [{ workload_id: "w-1", name: "web-01", environment: "prod", disposition: null }],
  dependencies: [],
  posture_assessment: { release_version: "v1" },
  cost_baseline: { currency: "GBP", total_amount_minor: 100, attributable_amount_minor: 100, unallocated_amount_minor: 0 },
  tco_result: { scenario_id: "run-1", currency: "GBP", projected_total_minor: 300, price_list_version: "2026.1" },
  disposition_decisions: [
    {
      decision_id: "d-1",
      workload_id: "w-1",
      disposition: "REHOST",
      rationale: "observed detail",
      confidence: 0.4,
      status: "PROPOSED",
      decided_by: null,
      decided_at: null,
    },
  ],
};

describe("renderResults", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
    setRunId("run-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders workloads, the cost/TCO summary and the pending decision", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(RESULTS_BODY)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "results");

    await renderResults(container, router);

    expect(container.querySelector("[data-slot='summary']")!.textContent).toContain("300 GBP");
    expect(container.querySelector("[data-slot='decisions']")!.textContent).toContain("web-01");
    expect(container.querySelector("[data-slot='decisions']")!.textContent).toContain("REHOST");
  });

  it("accepting a decision calls the accept route and refreshes the list", async () => {
    const accepted = { ...RESULTS_BODY.disposition_decisions[0], status: "ACCEPTED", decided_by: "user-1" };
    const refreshed = { ...RESULTS_BODY, disposition_decisions: [accepted] };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(RESULTS_BODY))
      .mockResolvedValueOnce(jsonResponse(accepted))
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "results");
    await renderResults(container, router);

    container.querySelector<HTMLElement>("[data-action='accept-decision']")!.click();

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='decisions']")!.textContent).toContain("ACCEPTED"),
    );
    expect(fetchMock.mock.calls[1][0]).toContain("/decisions/d-1/accept");
  });
});
