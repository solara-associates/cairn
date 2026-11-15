import { api, ApiError, PlanRevision } from "../api";
import { setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

function waveHtml(wave: PlanRevision["waves"][number]): string {
  const workloadRows = wave.workloads
    .map((workload) => {
      const constraints = workload.constraints.length
        ? `<ul>${workload.constraints
            .map((c) => `<li>${c.kind}: ${c.detail}</li>`)
            .join("")}</ul>`
        : "<p>No open constraints or risks.</p>";
      return `
        <li>
          <strong>${workload.workload_id}</strong> (${workload.disposition ?? "no disposition"})
          ${constraints}
        </li>
      `;
    })
    .join("");
  return `
    <section>
      <h3>Wave ${wave.wave_number}</h3>
      <ul>${workloadRows}</ul>
    </section>
  `;
}

export async function renderRoadmap(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const designId = session.designId;
  const planId = session.planId;
  if (!designId || !planId) {
    void router.go("patterns");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Migration roadmap</h1>
      <div data-slot="waves"><p>Loading...</p></div>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const wavesSlot = container.querySelector<HTMLElement>("[data-slot='waves']");

  try {
    const bundle = await api.getDesign(designId);
    const revision = await api.getPlanRevision(planId, bundle.plan.revision_number);
    if (wavesSlot) {
      wavesSlot.innerHTML = `
        <p>Wave count: ${revision.wave_count}</p>
        <p>Blocked workloads: ${revision.blocked_workload_ids.join(", ") || "none"}</p>
        ${revision.waves.map(waveHtml).join("")}
      `;
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the roadmap");
  }
}
