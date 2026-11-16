import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderTransformRun } from "../../src/screens/transform-run";
import { getSession, resetSession, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("renderTransformRun", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to projects when no project is selected", () => {
    resetSession();
    setToken("test-token");
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-run");
    router.register({ name: "projects", render: (c) => { c.textContent = "projects screen"; } });

    renderTransformRun(container, router);

    expect(container.textContent).toBe("projects screen");
  });

  it("triggers a transformation against a Git source and advances to the diff screen", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
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
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-run");
    router.register({ name: "transform-run", render: (c) => renderTransformRun(c, router) });
    router.register({ name: "transform-diff", render: (c) => { c.textContent = "diff screen"; } });

    renderTransformRun(container, router);

    (container.querySelector<HTMLInputElement>("#git_url")!).value = "https://example.test/repo.git";
    (container.querySelector<HTMLInputElement>("#git_ref")!).value = "main";
    container.querySelector("[data-action='trigger-transformation']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() => expect(container.textContent).toBe("diff screen"));
    expect(getSession().transformRunId).toBe("run-1");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.repository_ref).toEqual({
      kind: "GIT",
      url: "https://example.test/repo.git",
      ref: "main",
    });
  });

  it("switching to upload shows the archive id field instead of the git fields", () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-run");

    renderTransformRun(container, router);

    const select = container.querySelector<HTMLSelectElement>("#source_kind")!;
    select.value = "UPLOAD";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    expect(container.querySelector<HTMLElement>("[data-slot='git-fields']")!.hidden).toBe(true);
    expect(container.querySelector<HTMLElement>("[data-slot='upload-fields']")!.hidden).toBe(false);
  });

  it("rejects submission with a missing git ref", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-run");
    router.register({ name: "transform-run", render: (c) => renderTransformRun(c, router) });

    renderTransformRun(container, router);

    (container.querySelector<HTMLInputElement>("#git_url")!).value = "https://example.test/repo.git";
    (container.querySelector<HTMLInputElement>("#git_ref")!).value = "";
    container.querySelector("[data-action='trigger-transformation']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.querySelector("[data-slot='error']")!.textContent).toContain("required");
  });
});
