import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderTransformReview } from "../../src/screens/transform-review";
import { resetSession, setProjectId, setToken, setTransformRunId } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const EMPTY_THREAD = { run_id: "run-1", blocked: false, reviewed: false, comments: [] };

describe("renderTransformReview", () => {
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
    const router = new Router(container, "transform-review");
    router.register({ name: "transform-run", render: (c) => { c.textContent = "run screen"; } });

    renderTransformReview(container, router);

    expect(container.textContent).toBe("run screen");
  });

  it("shows 'not yet reviewed' before any comment exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(EMPTY_THREAD)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-review");

    await renderTransformReview(container, router);

    expect(container.querySelector("[data-slot='blocked']")!.textContent).toContain(
      "Not yet reviewed",
    );
    expect(container.querySelector("[data-slot='comments']")!.textContent).toContain(
      "No comments yet",
    );
  });

  it("posting a REQUEST_CHANGES comment visibly blocks the run", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(EMPTY_THREAD));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        run_id: "run-1",
        blocked: true,
        reviewed: true,
        comments: [
          {
            reviewer_actor_id: "user-1",
            decision: "REQUEST_CHANGES",
            body: "this breaks the dependency check",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-review");

    await renderTransformReview(container, router);

    (container.querySelector<HTMLSelectElement>("#decision")!).value = "REQUEST_CHANGES";
    (container.querySelector<HTMLTextAreaElement>("#body")!).value =
      "this breaks the dependency check";
    container.querySelector("[data-action='add-comment']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='blocked']")!.textContent).toContain("Blocked"),
    );
    expect(container.querySelector("[data-slot='comments']")!.textContent).toContain(
      "this breaks the dependency check",
    );
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body).toEqual({
      decision: "REQUEST_CHANGES",
      body: "this breaks the dependency check",
    });
  });

  it("a comment posted while the initial load is still in flight is not overwritten by it", async () => {
    // Regression for the CI flake in tests/e2e/transform-journey.test.ts
    // (always at the first REQUEST_CHANGES comment, never the second):
    // the initial `listReviewComments` GET and a fast `add-comment`
    // POST are two independent in-flight requests with no guaranteed
    // resolution order. Resolving the GET deliberately *after* the
    // POST reproduces exactly the ordering that was silently
    // overwriting the just-posted comment's "Blocked" status with the
    // GET's stale "Not yet reviewed" thread.
    let resolveGet!: (response: Response) => void;
    const getPromise = new Promise<Response>((resolve) => {
      resolveGet = resolve;
    });
    const fetchMock = vi.fn();
    fetchMock.mockReturnValueOnce(getPromise);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        run_id: "run-1",
        blocked: true,
        reviewed: true,
        comments: [
          {
            reviewer_actor_id: "user-1",
            decision: "REQUEST_CHANGES",
            body: "posted before the initial load resolved",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-review");

    // Not awaited -- the initial GET is still pending (`getPromise` has
    // not resolved yet), exactly like the e2e test's `void router.
    // go("transform-review")` not awaiting the screen's own render.
    const renderPromise = renderTransformReview(container, router);

    (container.querySelector<HTMLSelectElement>("#decision")!).value = "REQUEST_CHANGES";
    (container.querySelector<HTMLTextAreaElement>("#body")!).value =
      "posted before the initial load resolved";
    container.querySelector("[data-action='add-comment']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='blocked']")!.textContent).toContain("Blocked"),
    );

    // The initial GET resolves last, with the old, unblocked thread.
    resolveGet(jsonResponse(EMPTY_THREAD));
    await renderPromise;

    // It must not have clobbered the comment's render.
    expect(container.querySelector("[data-slot='blocked']")!.textContent).toContain("Blocked");
    expect(container.querySelector("[data-slot='comments']")!.textContent).toContain(
      "posted before the initial load resolved",
    );
  });

  it("rejects an empty comment body without calling the API", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(EMPTY_THREAD));
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-review");

    await renderTransformReview(container, router);
    container.querySelector("[data-action='add-comment']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(container.querySelector("[data-slot='error']")!.textContent).toContain("required");
  });
});
