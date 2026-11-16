import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderTransformDiff } from "../../src/screens/transform-diff";
import { resetSession, setProjectId, setToken, setTransformRunId } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const DIFF_RESPONSE = {
  run_id: "run-1",
  source_file_ids: ["s3.tf"],
  applied_count: 1,
  skipped_count: 1,
  unsupported_count: 1,
  files: [
    {
      source_file_id: "s3.tf",
      changed: true,
      unified_diff: "--- a/s3.tf\n+++ b/s3.tf\n@@ -1,3 +1,3 @@\n-  acl = \"public-read\"\n+  acl = \"private\"\n",
      original_content: 'acl = "public-read"',
      rendered_content: 'acl = "private"',
      applied_count: 1,
      skipped_count: 1,
      unsupported_count: 1,
      entries: [
        {
          rule_id: "tf-s3-bucket-inline-acl-deprecated",
          outcome: "APPLIED",
          reason: null,
          edits: [],
          detector_version: "d1",
          pattern_version: "p1",
          patcher_version: "pa1",
          mapping_release_version: null,
        },
        {
          rule_id: "tf-already-private",
          outcome: "SKIPPED",
          reason: "already private",
          edits: [],
          detector_version: "d1",
          pattern_version: "p1",
          patcher_version: "pa1",
          mapping_release_version: null,
        },
        {
          rule_id: "tf-unknown-resource",
          outcome: "UNSUPPORTED",
          reason: "no mapping for this resource type",
          edits: [],
          detector_version: "d1",
          pattern_version: "p1",
          patcher_version: "pa1",
          mapping_release_version: null,
        },
      ],
    },
  ],
};

describe("renderTransformDiff", () => {
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
    const router = new Router(container, "transform-diff");
    router.register({ name: "transform-run", render: (c) => { c.textContent = "run screen"; } });

    renderTransformDiff(container, router);

    expect(container.textContent).toBe("run screen");
  });

  it("shows every change's applied/skipped/unsupported status and reason, visibly distinguished", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(DIFF_RESPONSE)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-diff");

    await renderTransformDiff(container, router);

    const entries = container.querySelectorAll("[data-slot='entries'] li");
    expect(entries.length).toBe(3);
    expect(entries[0].getAttribute("data-outcome")).toBe("APPLIED");
    expect(entries[1].getAttribute("data-outcome")).toBe("SKIPPED");
    expect(entries[1].textContent).toContain("already private");
    expect(entries[2].getAttribute("data-outcome")).toBe("UNSUPPORTED");
    expect(entries[2].textContent).toContain("no mapping for this resource type");
    expect(container.querySelector("[data-slot='unified-diff']")!.textContent).toContain(
      'acl = "private"',
    );
  });

  it("navigates to validate/evidence/review from this screen", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(DIFF_RESPONSE)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "transform-diff");
    router.register({ name: "transform-diff", render: (c) => renderTransformDiff(c, router) });
    router.register({ name: "transform-validate", render: (c) => { c.textContent = "validate screen"; } });

    await renderTransformDiff(container, router);
    container.querySelector<HTMLElement>("[data-action='view-validate']")!.click();

    await vi.waitFor(() => expect(container.textContent).toBe("validate screen"));
  });
});
