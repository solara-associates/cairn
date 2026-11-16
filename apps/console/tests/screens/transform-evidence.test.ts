import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderTransformEvidence } from "../../src/screens/transform-evidence";
import { resetSession, setProjectId, setToken, setTransformRunId } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("renderTransformEvidence", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
    setTransformRunId("run-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to transform-run when no run is selected", () => {
    resetSession();
    setToken("test-token");
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-evidence");
    router.register({ name: "transform-run", render: (c) => { c.textContent = "run screen"; } });

    renderTransformEvidence(container, router);

    expect(container.textContent).toBe("run screen");
  });

  it("shows the sealed envelope's hash, outcome, signature and referenced outputs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          envelope: {
            package_id: "p-1:run-1",
            payload_hash: "abc123",
            previous_hash: null,
            outcome: "PASS",
            outputs: [
              { kind: "transformation_manifest", ref: "run-1", hash: "h1" },
              { kind: "transformation_diff", ref: "run-1", hash: "h2" },
            ],
            signature: { key_id: "local-evidence-key-1", algorithm: "FAKE_HMAC_SHA256", value: "sig" },
          },
          report: {
            run_id: "run-1",
            project_id: "p-1",
            run_number: 1,
            source_file_ids: ["s3.tf"],
            applied_count: 1,
            skipped_count: 0,
            unsupported_count: 0,
            created_by: "user-1",
            created_at: "2026-01-01T00:00:00Z",
            validation: null,
            review: null,
          },
        }),
      ),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-evidence");

    await renderTransformEvidence(container, router);

    const text = container.querySelector("[data-slot='evidence']")!.textContent!;
    expect(text).toContain("abc123");
    expect(text).toContain("PASS");
    expect(text).toContain("none -- first package for this project");
    expect(container.querySelector("[data-slot='outputs']")!.textContent).toContain(
      "transformation_manifest",
    );
    expect(container.querySelector("[data-slot='outputs']")!.textContent).toContain(
      "transformation_diff",
    );
  });
});
