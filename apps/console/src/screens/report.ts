import { api, ApiError } from "../api";
import { onClick, setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

export async function renderReport(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const projectId = session.projectId;
  const runId = session.runId;
  if (!projectId || !runId) {
    void router.go("projects");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Assessment report</h1>
      <pre data-slot="report-text">Loading...</pre>
      <button type="button" data-action="export-evidence">Export signed evidence package</button>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const textSlot = container.querySelector<HTMLElement>("[data-slot='report-text']");

  try {
    const report = await api.getAssessmentReport(projectId, runId);
    if (textSlot) {
      textSlot.textContent = report.rendered_text;
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the report");
  }

  onClick(container, "export-evidence", () => {
    void router.go("evidence");
  });
}
