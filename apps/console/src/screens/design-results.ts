import {
  api,
  ApiError,
  DesignExportBundle,
  DesignRevisionSummary,
  DiagramResponse,
  ResourceResolution,
} from "../api";
import { onClick, setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

/** Human-readable labels for the four distinct resolution markers --
 * never a bare enum value on screen (demo-readiness: a non-engineer
 * reads "approximate match, see note" not "APPROXIMATE"). */
const MARKER_LABEL: Record<string, string> = {
  EXACT: "Resolved",
  APPROXIMATE: "Approximate match",
  UNAVAILABLE: "Unavailable in this region/target",
  UNRESOLVED: "Unresolved -- no mapping found",
};

function resourceRow(resource: ResourceResolution): string {
  return `
    <li data-marker="${resource.marker}">
      <strong>${resource.shape_id}</strong>
      (${resource.source_provider}:${resource.source_service} -&gt;
      ${resource.target_service ?? "none"})
      -- <span data-slot="marker-label">${MARKER_LABEL[resource.marker] ?? resource.marker}</span>
      ${resource.detail ? `<p>${resource.detail}</p>` : ""}
    </li>
  `;
}

function revisionRow(revision: DesignRevisionSummary, isCurrent: boolean): string {
  return `
    <li>
      Revision ${revision.revision_number}${isCurrent ? " (current)" : ""}
      -- ${revision.content_hash.slice(0, 12)}&hellip; (${revision.created_at})
      <button type="button" data-action="view-revision" data-revision-number="${revision.revision_number}">
        View
      </button>
    </li>
  `;
}

export async function renderDesignResults(container: HTMLElement, router: Router): Promise<void> {
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
      <h1>Generated design</h1>
      <div data-slot="summary"><p>Loading...</p></div>
      <h2>Target resolution (resolved / approximate / unavailable / unresolved)</h2>
      <ul data-slot="resources"></ul>
      <h2>Revisions</h2>
      <ul data-slot="revisions"></ul>
      <div data-slot="comparison"></div>
      <button type="button" data-action="regenerate">Edit parameters and regenerate</button>
      <button type="button" data-action="view-roadmap">View migration roadmap</button>
      <button type="button" data-action="view-iac">View IaC preview</button>
      <button type="button" data-action="view-export">Export design</button>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const summarySlot = container.querySelector<HTMLElement>("[data-slot='summary']");
  const resourcesSlot = container.querySelector<HTMLElement>("[data-slot='resources']");
  const revisionsSlot = container.querySelector<HTMLElement>("[data-slot='revisions']");
  const comparisonSlot = container.querySelector<HTMLElement>("[data-slot='comparison']");

  let bundle: DesignExportBundle;
  let diagram: DiagramResponse;
  try {
    [bundle, diagram] = await Promise.all([
      api.getDesign(designId),
      api.getDesignDiagram(designId),
    ]);
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the design");
    return;
  }

  if (summarySlot) {
    summarySlot.innerHTML = `
      <p>Pattern: ${bundle.design.pattern_id}</p>
      <p>Revision: ${bundle.design.revision_number}</p>
      <p>Content hash: ${bundle.design.content_hash}</p>
      <p>Version stamps consistent: ${bundle.version_stamps_consistent ? "yes" : "no"}</p>
    `;
  }
  if (resourcesSlot) {
    resourcesSlot.innerHTML = diagram.shapes.map(resourceRow).join("") || "<li>No resources.</li>";
  }

  try {
    const revisions = await api.listDesignRevisions(designId);
    if (revisionsSlot) {
      revisionsSlot.innerHTML = revisions
        .map((revision) => revisionRow(revision, revision.revision_number === bundle.design.revision_number))
        .join("");
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load revision history");
  }

  onClick(container, "view-revision", async (_event, target) => {
    const revisionNumber = Number(target.dataset.revisionNumber);
    if (Number.isNaN(revisionNumber)) {
      return;
    }
    try {
      const revisionBundle = await api.getDesignRevision(designId, revisionNumber);
      if (comparisonSlot) {
        comparisonSlot.innerHTML = `
          <h3>Revision ${revisionNumber} -- parameters</h3>
          <pre>${JSON.stringify(Object.fromEntries(revisionBundle.design.parameters), null, 2)}</pre>
          <p>Content hash: ${revisionBundle.design.content_hash}</p>
        `;
      }
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not load that revision");
    }
  });

  onClick(container, "regenerate", () => {
    void router.go("parameterize");
  });
  onClick(container, "view-roadmap", () => {
    void router.go("roadmap");
  });
  onClick(container, "view-iac", () => {
    void router.go("iac");
  });
  onClick(container, "view-export", () => {
    void router.go("design-export");
  });
}
