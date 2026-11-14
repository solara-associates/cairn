import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderReport } from "../../src/screens/report";
import { resetSession, setProjectId, setRunId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("renderReport", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
    setRunId("run-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the backend's rendered_text verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          run_id: "run-1",
          run_coverage: { state: "COMPLETED", coverage: 1 },
          rendered_text: "# Assessment report -- run run-1",
          evidence_package_hash: null,
        }),
      ),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "report");

    await renderReport(container, router);

    expect(container.querySelector("[data-slot='report-text']")!.textContent).toBe(
      "# Assessment report -- run run-1",
    );
  });

  it("navigates to the evidence screen", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse({ run_id: "run-1", run_coverage: { state: "COMPLETED", coverage: 1 }, rendered_text: "x", evidence_package_hash: null }),
      ),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "report");
    router.register({ name: "report", render: (c) => renderReport(c, router) });
    router.register({ name: "evidence", render: (c) => { c.textContent = "evidence screen"; } });

    await renderReport(container, router);
    container.querySelector<HTMLElement>("[data-action='export-evidence']")!.click();

    await vi.waitFor(() => expect(container.textContent).toBe("evidence screen"));
  });
});
