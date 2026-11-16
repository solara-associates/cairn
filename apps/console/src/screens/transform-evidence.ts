import { api, ApiError } from "../api";
import { setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

/** R3-07: viewing 730's signed evidence record reference for this run --
 * the same "build and show the sealed envelope" pattern R1-18's own
 * `evidence.ts` already uses for an assessment run, reused here for a
 * transformation run's own evidence package. */
export async function renderTransformEvidence(
  container: HTMLElement,
  router: Router,
): Promise<void> {
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
      <h1>Signed evidence record</h1>
      <div data-slot="evidence"><p>Building...</p></div>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const evidenceSlot = container.querySelector<HTMLElement>("[data-slot='evidence']");

  try {
    const { envelope, report } = await api.buildTransformationEvidencePackage(runId);
    if (evidenceSlot) {
      evidenceSlot.innerHTML = `
        <p>Package: ${envelope.package_id}</p>
        <p>Payload hash: ${envelope.payload_hash}</p>
        <p>Outcome: ${envelope.outcome}</p>
        <p>Signed with: ${envelope.signature.key_id} (${envelope.signature.algorithm})</p>
        <p>Chained to previous package: ${envelope.previous_hash ?? "none -- first package for this project"}</p>
        <p>References run: ${report.run_id} (applied ${report.applied_count}, skipped
          ${report.skipped_count}, not supported ${report.unsupported_count})</p>
        <ul data-slot="outputs">
          ${envelope.outputs.map((output) => `<li>${output.kind}: ${output.ref}</li>`).join("")}
        </ul>
      `;
    }
  } catch (error) {
    showError(
      container,
      error instanceof ApiError ? error.message : "could not build the evidence record",
    );
  }
}
