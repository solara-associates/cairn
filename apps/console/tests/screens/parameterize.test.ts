import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderParameterize } from "../../src/screens/parameterize";
import { getSession, resetSession, setDesignIds, setPatternId, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const PATTERN = {
  id: "web-app",
  name: "Three-tier web application",
  category: "web_app",
  description: "A stateless web/API tier.",
  parameters: [
    {
      name: "compute_platform",
      type: "enum",
      description: "Target compute platform.",
      required: true,
      default: null,
      allowed_values: ["cloud_run", "gke"],
    },
    {
      name: "enable_cache",
      type: "boolean",
      description: "Whether a cache sits in front.",
      required: false,
      default: false,
      allowed_values: null,
    },
  ],
};

const DESIGN_SUMMARY = {
  design_id: "design-1",
  plan_id: "plan-1",
  revision_number: 1,
  content_hash: "hash-1",
  pattern_id: "web-app",
  target_provider: "gcp",
  parameters: { compute_platform: "cloud_run", enable_cache: false },
  resources: [],
  wave_count: 1,
  blocked_workload_ids: [],
};

describe("renderParameterize", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to patterns when neither a pattern nor a design is selected", async () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "parameterize");
    router.register({ name: "patterns", render: (c) => { c.textContent = "patterns screen"; } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse([PATTERN])));

    await renderParameterize(container, router);

    expect(container.textContent).toBe("patterns screen");
  });

  it("create mode: builds parameters/estate from the form and generates a design", async () => {
    setPatternId("web-app");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([PATTERN]))
      .mockResolvedValueOnce(jsonResponse(DESIGN_SUMMARY));
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "parameterize");
    router.register({ name: "design-results", render: (c) => { c.textContent = "design results screen"; } });

    await renderParameterize(container, router);

    (container.querySelector<HTMLSelectElement>("#param-compute_platform")!).value = "gke";
    (container.querySelector<HTMLTextAreaElement>("#resources")!).value = "res-1,aws,s3,europe-west2";

    container.querySelector("[data-action='generate-design']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() => expect(container.textContent).toBe("design results screen"));
    expect(getSession().designId).toBe("design-1");
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.pattern_id).toBe("web-app");
    expect(body.parameters.compute_platform).toBe("gke");
    expect(body.resources).toEqual([
      { resource_id: "res-1", provider: "aws", service: "s3", region: "europe-west2" },
    ]);
    expect(body.workloads).toHaveLength(1);
    expect(body.decisions).toHaveLength(1);
  });

  it("regenerate mode: prefills current parameters and calls the regenerate route", async () => {
    setDesignIds("design-1", "plan-1");
    const bundle = {
      design_id: "design-1",
      design: {
        design_id: "design-1",
        pattern_id: "web-app",
        parameters: [["compute_platform", "cloud_run"], ["enable_cache", false]],
      },
    };
    const regenerated = { ...DESIGN_SUMMARY, revision_number: 2 };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([PATTERN]))
      .mockResolvedValueOnce(jsonResponse(bundle))
      .mockResolvedValueOnce(jsonResponse(regenerated));
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "parameterize");
    router.register({ name: "design-results", render: (c) => { c.textContent = "design results screen"; } });

    await renderParameterize(container, router);

    expect((container.querySelector<HTMLSelectElement>("#param-compute_platform")!).value).toBe(
      "cloud_run",
    );
    // no estate/workload inputs in regenerate mode -- the estate is locked.
    expect(container.querySelector("#resources")).toBeNull();

    (container.querySelector<HTMLSelectElement>("#param-compute_platform")!).value = "gke";
    container.querySelector("[data-action='generate-design']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() => expect(container.textContent).toBe("design results screen"));
    const body = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(body.parameters.compute_platform).toBe("gke");
    expect(fetchMock.mock.calls[2][0]).toContain("/designs/design-1/regenerate");
  });
});
