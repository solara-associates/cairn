import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderDesignResults } from "../../src/screens/design-results";
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
  design: {
    design_id: "design-1",
    revision_id: "rev-1",
    revision_number: 1,
    content_hash: "hash-1",
    pattern_id: "web-app",
    parameters: [["compute_platform", "cloud_run"]],
    versions: VERSIONS,
  },
  diagram: { artefact_id: "d-1", revision_number: 1, content_hash: "d-hash", shape_count: 2, unresolved_shape_ids: [], versions: VERSIONS },
  plan: { plan_id: "plan-1", revision_number: 1, content_hash: "p-hash", wave_count: 1, workload_count: 1, blocked_workload_ids: [], versions: VERSIONS },
  iac: { artefact_id: "i-1", revision_number: 1, content_hash: "i-hash", gap_resource_ids: [], versions: VERSIONS },
  version_stamps_consistent: true,
};

const DIAGRAM = {
  artefact_id: "d-1",
  kind: "DIAGRAM",
  revision_number: 1,
  content_hash: "d-hash",
  rendered_content: "<xml/>",
  shapes: [
    {
      shape_id: "res-exact",
      source_provider: "aws",
      source_service: "secrets-manager",
      target_provider: "gcp",
      target_service: "secret-manager",
      marker: "EXACT",
      detail: null,
    },
    {
      shape_id: "res-approx",
      source_provider: "aws",
      source_service: "s3",
      target_provider: "gcp",
      target_service: "cloud-storage",
      marker: "APPROXIMATE",
      detail: "Consistency semantics differ.",
    },
  ],
};

const REVISIONS = [
  { revision_id: "rev-1", revision_number: 1, content_hash: "hash-1", created_at: "2026-11-15T00:00:00Z", parameters: { compute_platform: "cloud_run" } },
];

describe("renderDesignResults", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to patterns when no design has been generated", async () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "design-results");
    router.register({ name: "patterns", render: (c) => { c.textContent = "patterns screen"; } });

    await renderDesignResults(container, router);

    expect(container.textContent).toBe("patterns screen");
  });

  it("shows every resource's marker distinctly and lists revisions", async () => {
    setDesignIds("design-1", "plan-1");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(BUNDLE))
      .mockResolvedValueOnce(jsonResponse(DIAGRAM))
      .mockResolvedValueOnce(jsonResponse(REVISIONS));
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "design-results");

    await renderDesignResults(container, router);

    const resourcesHtml = container.querySelector("[data-slot='resources']")!.innerHTML;
    expect(resourcesHtml).toContain("Resolved");
    expect(resourcesHtml).toContain("Approximate match");
    expect(resourcesHtml).toContain("Consistency semantics differ.");

    expect(container.querySelector("[data-slot='revisions']")!.textContent).toContain(
      "Revision 1 (current)",
    );
  });

  it("navigates to roadmap/iac/export/regenerate on button click", async () => {
    setDesignIds("design-1", "plan-1");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(BUNDLE))
        .mockResolvedValueOnce(jsonResponse(DIAGRAM))
        .mockResolvedValueOnce(jsonResponse(REVISIONS)),
    );

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "design-results");
    router.register({ name: "roadmap", render: (c) => { c.textContent = "roadmap screen"; } });

    await renderDesignResults(container, router);
    container.querySelector<HTMLElement>("[data-action='view-roadmap']")!.click();

    await vi.waitFor(() => expect(container.textContent).toBe("roadmap screen"));
  });
});
