import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderDesignExport } from "../../src/screens/design-export";
import { resetSession, setDesignIds, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const VERSIONS = {
  pattern_catalogue_version: "2026.11.1",
  mapping_release_version: "2026.11.2",
  target_provider: "gcp",
};

const BUNDLE = {
  tenant_id: "t-1",
  project_id: "p-1",
  design_id: "design-1",
  design: { design_id: "design-1", revision_id: "rev-1", revision_number: 1, content_hash: "h", pattern_id: "web-app", parameters: [], versions: VERSIONS },
  diagram: { artefact_id: "d-1", revision_number: 1, content_hash: "h", shape_count: 1, unresolved_shape_ids: [], versions: VERSIONS },
  plan: { plan_id: "plan-1", revision_number: 1, content_hash: "h", wave_count: 1, workload_count: 1, blocked_workload_ids: [], versions: VERSIONS },
  iac: { artefact_id: "i-1", revision_number: 1, content_hash: "h", gap_resource_ids: ["res-2"], versions: VERSIONS },
  version_stamps_consistent: true,
};

describe("renderDesignExport", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to patterns when no design has been generated", async () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "design-export");
    router.register({ name: "patterns", render: (c) => { c.textContent = "patterns screen"; } });

    await renderDesignExport(container, router);

    expect(container.textContent).toBe("patterns screen");
  });

  it("shows the export summary and the full machine-readable bundle", async () => {
    setDesignIds("design-1", "plan-1");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(BUNDLE)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "design-export");

    await renderDesignExport(container, router);

    const summaryText = container.querySelector("[data-slot='summary']")!.textContent!;
    expect(summaryText).toContain("Version stamps consistent");
    expect(summaryText).toContain("yes");
    expect(summaryText).toContain("IaC gaps: 1");
    const bundleText = container.querySelector("[data-slot='bundle']")!.textContent!;
    expect(JSON.parse(bundleText)).toEqual(BUNDLE);
  });
});
