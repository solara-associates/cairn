import { api, ApiError, FileDiff, ManifestEntry, TransformationDiff } from "../api";
import { onClick, setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

/** Human-readable labels for the three distinct manifest outcomes --
 * never a bare enum value on screen (demo-readiness: a non-engineer
 * reads "applied" / "skipped, see reason" / "not supported, see
 * reason", not "APPLIED"/"SKIPPED"/"UNSUPPORTED"). Same discipline
 * R2-09's `MARKER_LABEL` already uses for its own distinct markers. */
const OUTCOME_LABEL: Record<string, string> = {
  APPLIED: "Applied",
  SKIPPED: "Skipped",
  UNSUPPORTED: "Not supported",
};

function entryRow(entry: ManifestEntry): string {
  return `
    <li data-outcome="${entry.outcome}">
      <strong>${entry.rule_id}</strong> --
      <span data-slot="outcome-label">${OUTCOME_LABEL[entry.outcome] ?? entry.outcome}</span>
      ${entry.reason ? `<p>Reason: ${entry.reason}</p>` : ""}
    </li>
  `;
}

function fileSection(file: FileDiff): string {
  return `
    <article data-file-id="${file.source_file_id}">
      <h3>${file.source_file_id}</h3>
      <p>
        Applied: ${file.applied_count}, skipped: ${file.skipped_count},
        not supported: ${file.unsupported_count}
      </p>
      <h4>Per-change status</h4>
      <ul data-slot="entries">${file.entries.map(entryRow).join("")}</ul>
      <h4>Unified diff</h4>
      <pre data-slot="unified-diff">${file.changed ? file.unified_diff : "(no change to this file)"}</pre>
    </article>
  `;
}

/** R3-07: inspecting 728's unified diff, with every manifest entry's
 * applied/skipped/unsupported status and reason visibly distinguished
 * -- not just present in the underlying data (spec S16's R3-04 row,
 * surfaced here the way this story's own acceptance text asks for). */
export async function renderTransformDiff(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const runId = session.transformRunId;
  if (!runId) {
    void router.go("transform-run");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Transformation diff</h1>
      <div data-slot="summary"><p>Loading...</p></div>
      <div data-slot="files"></div>
      <button type="button" data-action="view-validate">Run validation</button>
      <button type="button" data-action="view-evidence">View evidence record</button>
      <button type="button" data-action="view-review">Review and comment</button>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const summarySlot = container.querySelector<HTMLElement>("[data-slot='summary']");
  const filesSlot = container.querySelector<HTMLElement>("[data-slot='files']");

  let diff: TransformationDiff;
  try {
    diff = await api.getTransformationDiff(runId);
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the diff");
    return;
  }

  if (summarySlot) {
    summarySlot.innerHTML = `
      <p>Run: ${diff.run_id}</p>
      <p>
        Applied: ${diff.applied_count}, skipped: ${diff.skipped_count},
        not supported: ${diff.unsupported_count}
      </p>
    `;
  }
  if (filesSlot) {
    filesSlot.innerHTML = diff.files.map(fileSection).join("") || "<p>No files in this run.</p>";
  }

  onClick(container, "view-validate", () => {
    void router.go("transform-validate");
  });
  onClick(container, "view-evidence", () => {
    void router.go("transform-evidence");
  });
  onClick(container, "view-review", () => {
    void router.go("transform-review");
  });
}
