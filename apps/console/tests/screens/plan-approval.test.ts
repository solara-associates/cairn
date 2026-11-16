import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderPlanApproval } from "../../src/screens/plan-approval";
import { resetSession, setDesignIds, setProjectId, setToken } from "../../src/state";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const EMPTY_APPROVAL = { revision_id: "rev-1", blocked: false, reviewed: false, comments: [] };

const VIEW_WITH_RECOVERY_PLAN = {
  revision: {
    revision_id: "rev-1",
    tenant_id: "t-1",
    project_id: "p-1",
    design_id: "design-1",
    revision_number: 1,
    content_hash: "hash-1",
    mutation_class: "REVERSIBLE_EXTERNAL_MUTATION",
    created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z",
    diff: [
      {
        resource_id: "res-1",
        action: "CREATE",
        source_provider: "aws",
        source_service: "s3",
        target_provider: "gcp",
        target_service: "cloud-storage",
        approximate: false,
        detail: null,
      },
    ],
    resource_list: ["res-1"],
    reversible: true,
    provider_preview: {},
  },
  risk_tier: "TIER_1",
  recovery_plan: {
    strategy: "ROLLBACK",
    plan_ref: "tf-plan-ref-1",
    preconditions: "rollback reference validated",
    authority: "PROJECT_OWNER",
    evidence: "before/during/after state snapshots captured",
    failure_handling: "escalate to runbook",
  },
  evidence_to_capture: "before/during/after state snapshots captured",
  approval: EMPTY_APPROVAL,
};

const VIEW_WITHOUT_RECOVERY_PLAN = {
  ...VIEW_WITH_RECOVERY_PLAN,
  recovery_plan: null,
  evidence_to_capture:
    "No recovery plan has been recorded for this revision yet -- nothing is committed to capture, and this mutation cannot be approved from this console until one is.",
};

describe("renderPlanApproval", () => {
  beforeEach(() => {
    resetSession();
    setToken("test-token");
    setProjectId("p-1");
    setDesignIds("design-1", "plan-1");
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects to patterns when no design has been generated", async () => {
    resetSession();
    setToken("test-token");
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "plan-approval");
    router.register({ name: "patterns", render: (c) => { c.textContent = "patterns screen"; } });

    await renderPlanApproval(container, router);

    expect(container.textContent).toBe("patterns screen");
  });

  it("shows the exact revision, diff, mutation class, recovery plan and evidence after proposing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(VIEW_WITH_RECOVERY_PLAN)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "plan-approval");

    await renderPlanApproval(container, router);

    (container.querySelector<HTMLSelectElement>("#mutation_class")!).value =
      "REVERSIBLE_EXTERNAL_MUTATION";
    (container.querySelector<HTMLInputElement>("#plan_ref")!).value = "tf-plan-ref-1";
    (container.querySelector<HTMLInputElement>("#preconditions")!).value = "rollback reference validated";
    (container.querySelector<HTMLInputElement>("#authority")!).value = "PROJECT_OWNER";
    (container.querySelector<HTMLInputElement>("#evidence")!).value =
      "before/during/after state snapshots captured";
    (container.querySelector<HTMLInputElement>("#failure_handling")!).value = "escalate to runbook";
    container.querySelector("[data-action='propose-plan']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='console']")!.hasAttribute("hidden")).toBe(false),
    );

    expect(container.querySelector("[data-slot='revision']")!.textContent).toContain(
      "REVERSIBLE_EXTERNAL_MUTATION",
    );
    expect(container.querySelector("[data-slot='diff']")!.textContent).toContain("res-1");
    expect(container.querySelector("[data-slot='recovery-plan']")!.textContent).toContain("ROLLBACK");
    expect(container.querySelector("[data-slot='evidence']")!.textContent).toContain(
      "state snapshots captured",
    );
  });

  it("shows an honest 'no recovery plan recorded' message when none was proposed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(VIEW_WITHOUT_RECOVERY_PLAN)));

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "plan-approval");

    await renderPlanApproval(container, router);
    container.querySelector("[data-action='propose-plan']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='no-recovery-plan']")).not.toBeNull(),
    );
    expect(container.querySelector("[data-slot='evidence']")!.textContent).toContain(
      "No recovery plan has been recorded",
    );
  });

  it("rejects a partially-filled recovery plan without calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "plan-approval");

    await renderPlanApproval(container, router);
    (container.querySelector<HTMLInputElement>("#plan_ref")!).value = "tf-plan-ref-1";
    container.querySelector("[data-action='propose-plan']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.querySelector("[data-slot='error']")!.textContent).toContain(
      "every field filled in, or none at all",
    );
  });

  it("a 403 from the API on APPROVE (incomplete recovery plan) is shown, not silently swallowed", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(VIEW_WITHOUT_RECOVERY_PLAN));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { title: "cannot be approved from this console without a recorded recovery plan" },
        403,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "plan-approval");

    await renderPlanApproval(container, router);
    container.querySelector("[data-action='propose-plan']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='console']")!.hasAttribute("hidden")).toBe(false),
    );

    (container.querySelector<HTMLSelectElement>("#decision")!).value = "APPROVE";
    (container.querySelector<HTMLTextAreaElement>("#body")!).value = "approving anyway";
    container.querySelector("[data-action='decide']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='error']")!.hasAttribute("hidden")).toBe(false),
    );
    expect(container.querySelector("[data-slot='error']")!.textContent).toContain(
      "recorded recovery plan",
    );
  });

  it("posting an APPROVE decision with a complete recovery plan updates the approval status", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse(VIEW_WITH_RECOVERY_PLAN));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        revision_id: "rev-1",
        blocked: false,
        reviewed: true,
        comments: [
          {
            reviewer_actor_id: "user-1",
            decision: "APPROVE",
            body: "looks good",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "plan-approval");

    await renderPlanApproval(container, router);
    container.querySelector("[data-action='propose-plan']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='console']")!.hasAttribute("hidden")).toBe(false),
    );

    (container.querySelector<HTMLSelectElement>("#decision")!).value = "APPROVE";
    (container.querySelector<HTMLTextAreaElement>("#body")!).value = "looks good";
    container.querySelector("[data-action='decide']")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );

    await vi.waitFor(() =>
      expect(container.querySelector("[data-slot='blocked']")!.textContent).toContain("Approved"),
    );
    expect(container.querySelector("[data-slot='comments']")!.textContent).toContain("looks good");
  });
});
