import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderPatterns } from "../../src/screens/patterns";
import { getSession, resetSession, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const PATTERNS = [
  {
    id: "web-app",
    name: "Three-tier web application",
    category: "web_app",
    description: "A stateless web/API tier.",
    parameters: [],
  },
];

describe("renderPatterns", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to projects when no project is selected", async () => {
    resetSession();
    setToken("test-token");
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "patterns");
    router.register({ name: "projects", render: (c) => { c.textContent = "projects screen"; } });

    await renderPatterns(container, router);

    expect(container.textContent).toBe("projects screen");
  });

  it("lists patterns and selecting one stores it and moves to parameterize", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(PATTERNS)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "patterns");
    router.register({ name: "parameterize", render: (c) => { c.textContent = "parameterize screen"; } });

    await renderPatterns(container, router);

    expect(container.querySelector("[data-slot='pattern-list']")!.textContent).toContain(
      "Three-tier web application",
    );

    container.querySelector<HTMLElement>("[data-action='select-pattern']")!.click();

    await vi.waitFor(() => expect(container.textContent).toBe("parameterize screen"));
    expect(getSession().patternId).toBe("web-app");
  });
});
