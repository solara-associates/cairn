import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderRoadmap } from "../../src/screens/roadmap";
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
  plan: { plan_id: "plan-1", revision_number: 1, content_hash: "h", wave_count: 2, workload_count: 2, blocked_workload_ids: ["wl-2"], versions: VERSIONS },
  iac: { artefact_id: "i-1", revision_number: 1, content_hash: "h", gap_resource_ids: [], versions: VERSIONS },
  version_stamps_consistent: true,
};

const PLAN_REVISION = {
  plan_id: "plan-1",
  revision_id: "plan-rev-1",
  revision_number: 1,
  content_hash: "h",
  wave_count: 2,
  blocked_workload_ids: ["wl-2"],
  waves: [
    { wave_number: 1, workloads: [{ workload_id: "wl-1", disposition: "REHOST", constraints: [] }] },
    {
      wave_number: 2,
      workloads: [
        {
          workload_id: "wl-2",
          disposition: null,
          constraints: [{ kind: "PENDING_DISPOSITION", detail: "workload wl-2 has no recorded 6R disposition decision" }],
        },
      ],
    },
  ],
};

describe("renderRoadmap", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to patterns when no design/plan is in session", async () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "roadmap");
    router.register({ name: "patterns", render: (c) => { c.textContent = "patterns screen"; } });

    await renderRoadmap(container, router);

    expect(container.textContent).toBe("patterns screen");
  });

  it("renders every wave, its workloads and open constraints/risks", async () => {
    setDesignIds("design-1", "plan-1");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(BUNDLE)).mockResolvedValueOnce(jsonResponse(PLAN_REVISION)),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "roadmap");

    await renderRoadmap(container, router);

    const html = container.querySelector("[data-slot='waves']")!.innerHTML;
    expect(html).toContain("Wave 1");
    expect(html).toContain("Wave 2");
    expect(html).toContain("wl-2");
    expect(html).toContain("PENDING_DISPOSITION");
  });
});
