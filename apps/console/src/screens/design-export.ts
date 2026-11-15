import { api, ApiError } from "../api";
import { setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

export async function renderDesignExport(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const designId = session.designId;
  if (!designId) {
    void router.go("patterns");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Export design</h1>
      <div data-slot="summary"><p>Loading...</p></div>
      <h2>Machine-readable export bundle</h2>
      <pre data-slot="bundle"></pre>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const summarySlot = container.querySelector<HTMLElement>("[data-slot='summary']");
  const bundleSlot = container.querySelector<HTMLElement>("[data-slot='bundle']");

  try {
    const bundle = await api.getDesign(designId);
    if (summarySlot) {
      summarySlot.innerHTML = `
        <p>Design ${bundle.design_id}, revision ${bundle.design.revision_number}</p>
        <p>Plan ${bundle.plan.plan_id} -- ${bundle.plan.wave_count} wave(s),
          ${bundle.plan.blocked_workload_ids.length} blocked workload(s)</p>
        <p>IaC gaps: ${bundle.iac.gap_resource_ids.length}</p>
        <p>Version stamps consistent across design/diagram/plan/IaC:
          ${bundle.version_stamps_consistent ? "yes" : "no -- do not export this design"}</p>
      `;
    }
    if (bundleSlot) {
      bundleSlot.textContent = JSON.stringify(bundle, null, 2);
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not export the design");
  }
}
