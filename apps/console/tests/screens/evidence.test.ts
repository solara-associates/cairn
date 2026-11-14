import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderEvidence } from "../../src/screens/evidence";
import { resetSession, setProjectId, setRunId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("renderEvidence", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
    setRunId("run-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the sealed envelope's hash and signature and the final report text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          envelope: {
            package_id: "p-1:run-1",
            payload_hash: "abc123",
            previous_hash: null,
            signature: { key_id: "local-evidence-key-1", algorithm: "FAKE_HMAC_SHA256", value: "sig" },
          },
          report: {
            run_id: "run-1",
            run_coverage: { state: "COMPLETED", coverage: 1 },
            rendered_text: "Evidence package hash: abc123",
            evidence_package_hash: "abc123",
          },
        }),
      ),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "evidence");

    await renderEvidence(container, router);

    const evidenceText = container.querySelector("[data-slot='evidence']")!.textContent!;
    expect(evidenceText).toContain("abc123");
    expect(evidenceText).toContain("none -- first package for this project");
    expect(container.querySelector("[data-slot='report-text']")!.textContent).toContain("abc123");
  });
});
