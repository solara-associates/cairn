import { api, ApiError, AssessmentRunResults, DispositionDecision, Workload } from "../api";
import { onClick, onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

const DISPOSITIONS = ["REHOST", "REPLATFORM", "REFACTOR", "REPURCHASE", "RETIRE", "RETAIN"];

function workloadName(workloads: Workload[] | null, workloadId: string): string {
  return workloads?.find((w) => w.workload_id === workloadId)?.name ?? workloadId;
}

function decisionRow(decision: DispositionDecision, workloads: Workload[] | null): string {
  const reviewed = decision.status !== "PROPOSED";
  return `
    <li data-decision-id="${decision.decision_id}">
      <strong>${workloadName(workloads, decision.workload_id)}</strong>
      -- ${decision.disposition} (${decision.status}, confidence ${decision.confidence})
      <p>${decision.rationale}</p>
      ${
        reviewed
          ? ""
          : `
        <button type="button" data-action="accept-decision" data-decision-id="${decision.decision_id}">Accept</button>
        <form data-action="reject-decision" data-decision-id="${decision.decision_id}">
          <input name="reason" placeholder="reason" required />
          <button type="submit">Reject</button>
        </form>
        <form data-action="amend-decision" data-decision-id="${decision.decision_id}">
          <select name="disposition">
            ${DISPOSITIONS.map((d) => `<option value="${d}">${d}</option>`).join("")}
          </select>
          <input name="rationale" placeholder="rationale" required />
          <input name="confidence" type="number" min="0" max="1" step="0.1" value="0.8" />
          <button type="submit">Amend</button>
        </form>
      `
      }
    </li>
  `;
}

export async function renderResults(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  if (!session.projectId || !session.runId) {
    void router.go("projects");
    return;
  }
  const projectId: string = session.projectId;
  const runId: string = session.runId;

  setHtml(
    container,
    `
    <section>
      <h1>Assessment results</h1>
      <div data-slot="summary"><p>Loading...</p></div>
      <h2>Workloads and 6R decisions</h2>
      <ul data-slot="decisions"></ul>
      <button type="button" data-action="view-report">View report</button>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const summarySlot = container.querySelector<HTMLElement>("[data-slot='summary']");
  const decisionsSlot = container.querySelector<HTMLElement>("[data-slot='decisions']");

  async function refresh(): Promise<AssessmentRunResults | undefined> {
    try {
      const results = await api.getAssessmentRunResults(projectId, runId);
      if (summarySlot) {
        summarySlot.innerHTML = `
          <p>Posture: ${results.posture_assessment ? "evaluated" : "not available"}</p>
          <p>Cost baseline: ${results.cost_baseline ? `${results.cost_baseline.total_amount_minor} ${results.cost_baseline.currency} minor units` : "not available"}</p>
          <p>TCO: ${results.tco_result ? `${results.tco_result.projected_total_minor} ${results.tco_result.currency} minor units (projected)` : "not available"}</p>
        `;
      }
      if (decisionsSlot) {
        const decisions = results.disposition_decisions ?? [];
        decisionsSlot.innerHTML = decisions.length
          ? decisions.map((d) => decisionRow(d, results.workloads)).join("")
          : "<li>No 6R decisions yet.</li>";
      }
      return results;
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not load results");
      return undefined;
    }
  }

  onClick(container, "accept-decision", async (_event, target) => {
    const decisionId = target.dataset.decisionId;
    if (!decisionId) return;
    try {
      await api.acceptDecision(projectId, runId, decisionId);
      await refresh();
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not accept the decision");
    }
  });

  onSubmit(container, "reject-decision", async (_event, form) => {
    const decisionId = form.dataset.decisionId;
    const reason = formValue(form, "reason").trim();
    if (!decisionId || !reason) {
      showError(container, "A reason is required to reject a decision.");
      return;
    }
    try {
      await api.rejectDecision(projectId, runId, decisionId, reason);
      await refresh();
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not reject the decision");
    }
  });

  onSubmit(container, "amend-decision", async (_event, form) => {
    const decisionId = form.dataset.decisionId;
    const disposition = formValue(form, "disposition");
    const rationale = formValue(form, "rationale").trim();
    const confidence = Number(formValue(form, "confidence"));
    if (!decisionId || !rationale) {
      showError(container, "A rationale is required to amend a decision.");
      return;
    }
    try {
      await api.amendDecision(projectId, runId, decisionId, { disposition, rationale, confidence });
      await refresh();
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not amend the decision");
    }
  });

  onClick(container, "view-report", () => {
    void router.go("report");
  });

  await refresh();
}
