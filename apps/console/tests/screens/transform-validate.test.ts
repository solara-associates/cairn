import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderTransformValidate } from "../../src/screens/transform-validate";
import { resetSession, setProjectId, setToken, setTransformRunId } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const RUN_WITHOUT_VALIDATION = {
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
};

describe("renderTransformValidate", () => {
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
    const router = new Router(container, "transform-validate");
    router.register({ name: "transform-run", render: (c) => { c.textContent = "run screen"; } });

    renderTransformValidate(container, router);

    expect(container.textContent).toBe("run screen");
  });

  it("a failing check visibly blocks the proceed button, not just advisory text", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(RUN_WITHOUT_VALIDATION));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        run_id: "run-1",
        approved: false,
        results: [{ check_id: "static-reparse", passed: false, reason: "syntax broke" }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-validate");

    await renderTransformValidate(container, router);
    container.querySelector<HTMLElement>("[data-action='run-validation']")!.click();

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='approved']")!.textContent).toContain("no"),
    );
    const proceedButton = container.querySelector<HTMLButtonElement>("[data-action='proceed']")!;
    expect(proceedButton.disabled).toBe(true);
    expect(container.querySelector<HTMLElement>("[data-slot='blocked-notice']")!.hidden).toBe(false);
    const resultRow = container.querySelector("[data-slot='results'] li")!;
    expect(resultRow.getAttribute("data-passed")).toBe("false");
    expect(resultRow.textContent).toContain("syntax broke");
  });

  it("a fully passing validation run enables the proceed button", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(RUN_WITHOUT_VALIDATION));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        run_id: "run-1",
        approved: true,
        results: [{ check_id: "static-reparse", passed: true, reason: null }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-validate");
    router.register({ name: "transform-validate", render: (c) => renderTransformValidate(c, router) });
    router.register({ name: "transform-review", render: (c) => { c.textContent = "review screen"; } });

    await renderTransformValidate(container, router);
    container.querySelector<HTMLElement>("[data-action='run-validation']")!.click();

    await vi.waitFor(() => {
      const proceedButton = container.querySelector<HTMLButtonElement>("[data-action='proceed']")!;
      expect(proceedButton.disabled).toBe(false);
    });

    container.querySelector<HTMLElement>("[data-action='proceed']")!.click();
    await vi.waitFor(() => expect(container.textContent).toBe("review screen"));
  });

  it("loads an already-recorded validation outcome on render", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          ...RUN_WITHOUT_VALIDATION,
          validation: {
            run_id: "run-1",
            approved: true,
            results: [{ check_id: "static-reparse", passed: true, reason: null }],
          },
        }),
      ),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-validate");

    await renderTransformValidate(container, router);

    expect(container.querySelector("[data-slot='approved']")!.textContent).toContain("yes");
    expect(container.querySelector<HTMLButtonElement>("[data-action='proceed']")!.disabled).toBe(false);
  });
});
