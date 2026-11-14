import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderProjects } from "../../src/screens/projects";
import { resetSession, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("renderProjects", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists existing projects and selects one to continue", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([{ project_id: "p-1", tenant_id: "t-1", name: "Acme Migration", customer_name: null, created_at: "now", updated_at: "now" }]));
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "projects");
    router.register({ name: "projects", render: (c) => renderProjects(c, router) });
    router.register({ name: "connect", render: (c) => { c.textContent = "connect screen"; } });

    await renderProjects(container, router);

    expect(container.querySelector("[data-slot='project-list']")!.textContent).toContain(
      "Acme Migration",
    );

    const selectButton = container.querySelector<HTMLElement>("[data-action='select-project']")!;
    selectButton.click();
    await vi.waitFor(() => expect(container.textContent).toBe("connect screen"));
  });

  it("creates a project and refreshes the list", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ project_id: "p-2", tenant_id: "t-1", name: "New Co", customer_name: null, created_at: "now", updated_at: "now" }))
      .mockResolvedValueOnce(
        jsonResponse([{ project_id: "p-2", tenant_id: "t-1", name: "New Co", customer_name: null, created_at: "now", updated_at: "now" }]),
      );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "projects");
    await renderProjects(container, router);

    const nameInput = container.querySelector<HTMLInputElement>("#name")!;
    nameInput.value = "New Co";
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='project-list']")!.textContent).toContain("New Co"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
