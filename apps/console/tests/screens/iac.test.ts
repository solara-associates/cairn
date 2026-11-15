import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderIac } from "../../src/screens/iac";
import { resetSession, setDesignIds, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const IAC = {
  artefact_id: "i-1",
  kind: "IAC",
  revision_number: 1,
  content_hash: "h",
  disclaimer:
    "CAIRN IaC plan preview -- PLAN ONLY. Not executed. Not applied. No Terraform binary was invoked...",
  rendered_content: "# preview\nresource gap...",
  gap_resource_ids: ["res-2"],
  resources: [
    { resource_id: "res-1", source_provider: "aws", source_service: "secrets-manager", target_provider: "gcp", target_service: "secret-manager", status: "PLANNED", approximate: false, detail: null },
    { resource_id: "res-2", source_provider: "aws", source_service: "no-such-service", target_provider: "", target_service: null, status: "GAP", approximate: false, detail: "no mapping from aws:no-such-service to gcp" },
  ],
};

describe("renderIac", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to patterns when no design has been generated", async () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "iac");
    router.register({ name: "patterns", render: (c) => { c.textContent = "patterns screen"; } });

    await renderIac(container, router);

    expect(container.textContent).toBe("patterns screen");
  });

  it("shows the plan-only disclaimer, planned/gap resources and the rendered preview", async () => {
    setDesignIds("design-1", "plan-1");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(IAC)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "iac");

    await renderIac(container, router);

    expect(container.querySelector("[data-slot='disclaimer']")!.textContent).toContain("PLAN ONLY");
    const resourcesHtml = container.querySelector("[data-slot='resources']")!.innerHTML;
    expect(resourcesHtml).toContain("Planned");
    expect(resourcesHtml).toContain("Gap -- no resource planned");
    expect(container.querySelector("[data-slot='rendered']")!.textContent).toContain("# preview");
  });
});
