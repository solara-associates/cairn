import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderConnect } from "../../src/screens/connect";
import { getSession, resetSession, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("renderConnect", () => {
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
    const router = new Router(container, "connect");
    router.register({ name: "projects", render: (c) => { c.textContent = "projects screen"; } });

    renderConnect(container, router);

    expect(container.textContent).toBe("projects screen");
  });

  it("adds a file to the pending list and starts the assessment run", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({ run_id: "run-1", state: "QUEUED", coverage: 0, completed_stages: [], pending_stages: [], failures: [] }, 202),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "connect");
    router.register({ name: "connect", render: (c) => renderConnect(c, router) });
    router.register({ name: "run", render: (c) => { c.textContent = "run screen"; } });

    renderConnect(container, router);

    (container.querySelector<HTMLSelectElement>("#source_format")!).value = "csv";
    (container.querySelector<HTMLTextAreaElement>("#content")!).value = "hostname\nweb-01";
    container.querySelector("[data-action='add-file']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    expect(container.querySelector("[data-slot='file-list']")!.textContent).toContain("csv");

    container.querySelector<HTMLElement>("[data-action='start-assessment']")!.click();

    await vi.waitFor(() => expect(container.textContent).toBe("run screen"));
    expect(getSession().runId).toBe("run-1");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.files).toEqual([{ source_format: "csv", content: "hostname\nweb-01" }]);
  });
});
