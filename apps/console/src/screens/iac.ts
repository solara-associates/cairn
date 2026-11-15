import { api, ApiError, IacResourcePlan } from "../api";
import { setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

function resourceRow(resource: IacResourcePlan): string {
  const label = resource.status === "GAP" ? "Gap -- no resource planned" : "Planned";
  return `
    <li>
      <strong>${resource.resource_id}</strong>
      -- ${label}${resource.approximate ? " (approximate mapping)" : ""}
      ${resource.detail ? `<p>${resource.detail}</p>` : ""}
    </li>
  `;
}

export async function renderIac(container: HTMLElement, router: Router): Promise<void> {
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
      <h1>Infrastructure-as-code preview</h1>
      <p data-slot="disclaimer"></p>
      <ul data-slot="resources"></ul>
      <h2>Rendered preview</h2>
      <pre data-slot="rendered"></pre>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const disclaimerSlot = container.querySelector<HTMLElement>("[data-slot='disclaimer']");
  const resourcesSlot = container.querySelector<HTMLElement>("[data-slot='resources']");
  const renderedSlot = container.querySelector<HTMLElement>("[data-slot='rendered']");

  try {
    const iac = await api.getDesignIac(designId);
    if (disclaimerSlot) {
      disclaimerSlot.textContent = iac.disclaimer;
    }
    if (resourcesSlot) {
      resourcesSlot.innerHTML = iac.resources.map(resourceRow).join("") || "<li>No resources.</li>";
    }
    if (renderedSlot) {
      renderedSlot.textContent = iac.rendered_content;
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the IaC preview");
  }
}
