import { api, ApiError } from "../api";
import { setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

export async function renderEvidence(container: HTMLElement, router: Router): Promise<void> {
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
      <h1>Signed evidence package</h1>
      <div data-slot="evidence"><p>Building...</p></div>
      <pre data-slot="report-text"></pre>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const evidenceSlot = container.querySelector<HTMLElement>("[data-slot='evidence']");
  const textSlot = container.querySelector<HTMLElement>("[data-slot='report-text']");

  try {
    const { envelope, report } = await api.buildEvidencePackage(projectId, runId);
    if (evidenceSlot) {
      evidenceSlot.innerHTML = `
        <p>Package: ${envelope.package_id}</p>
        <p>Payload hash: ${envelope.payload_hash}</p>
        <p>Signed with: ${envelope.signature.key_id} (${envelope.signature.algorithm})</p>
        <p>Chained to previous package: ${envelope.previous_hash ?? "none -- first package for this project"}</p>
      `;
    }
    if (textSlot) {
      textSlot.textContent = report.rendered_text;
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not build the evidence package");
  }
}
